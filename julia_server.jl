"""
Tortuosity Julia HTTP server.

Keeps Tortuosity.jl and CUDA warm in a single long-running process so that the
compilation cost is paid once at startup rather than on every Streamlit request.

Endpoints
---------
POST /tortuosity
    Multipart form fields:
        image  – raw bytes of a numpy .npy Bool array (written by np.save)
        D      – (optional) raw bytes of a numpy .npy Float32 array of per-voxel
                  diffusivity values, same shape as image.  Omit this field for
                  the standard binary (all-open-pore = 1) case.
        axis   – "x", "y", or "z"
        reltol – relative solver tolerance as a decimal string (e.g. "1e-5")
        gpu    – "true" or "false"
    Returns 202 JSON: {"job_id": "<uuid>"}

GET /job/<id>
    Returns 200 JSON:
        pending/running: {"status": "pending"|"running"}
        done:            {"status": "done", "tau": <float>}
        error:           {"status": "error", "error": "<message>"}

GET /job/<id>/conc
    Returns 200 binary: .npz bytes of the concentration field (Float32 3-D array).
    Key inside the archive is "conc".  Read in Python with:
        np.load(io.BytesIO(resp.content))["conc"]
    Only available when status == "done".

DELETE /job/<id>
    Cancels a pending/running job and removes it from the store.
    Returns 204.

GET /health
    Returns 200 JSON: {"status": "ok", "gpus": <int>}

GPU worker pool
---------------
One worker task is spawned per available GPU (or one CPU worker if no GPU is
present).  All workers share a single Channel{String} job queue.  Each worker
binds itself to its assigned GPU via CUDA.device!() so jobs naturally spread
across GPUs.  If more jobs arrive than there are GPUs, they queue behind the
workers — no request is ever dropped.
"""

using HTTP
using Tortuosity
using Tortuosity: tortuosity, vec_to_grid
using NPZ
using UUIDs

# CUDA is loaded conditionally so the server still works on CPU-only machines.
const CUDA_AVAILABLE = try
    using CUDA
    CUDA.functional()
catch
    false
end

# ── Job store ─────────────────────────────────────────────────────────────────

@enum JobStatus PENDING RUNNING DONE ERROR_STATE

mutable struct JobRecord
    status::JobStatus
    # inputs (held until job starts, then cleared to free memory)
    img::Array{Bool}
    D::Union{Nothing, Array{Float32}}
    axis::Symbol
    reltol::Float32
    gpu::Bool
    # outputs
    tau::Float64
    conc::Array{Float32, 3}
    err::String
end

const JOB_QUEUE = Channel{String}(256)
const JOB_STORE = Dict{String, JobRecord}()
const JOB_LOCK  = ReentrantLock()

function release_job_inputs!(rec::JobRecord)
    rec.img = Array{Bool}(undef, 0, 0, 0)
    rec.D = nothing
    return nothing
end

function release_job_buffers!(rec::JobRecord)
    release_job_inputs!(rec)
    rec.conc = Array{Float32, 3}(undef, 0, 0, 0)
    return nothing
end

function maybe_reclaim_memory!(use_gpu::Bool)
    # Keep long-running workers from accumulating unreachable allocations.
    GC.gc(false)
    if use_gpu && CUDA_AVAILABLE
        try
            CUDA.synchronize()
            CUDA.reclaim()
        catch e
            @warn "CUDA memory reclaim failed" exception=e
        end
    end
    return nothing
end

function new_job!(img::Array{Bool}, D::Union{Nothing, Array{Float32}}, axis, reltol, gpu)
    id  = string(uuid4())
    rec = JobRecord(PENDING, img, D, axis, reltol, gpu,
                    0.0, Array{Float32,3}(undef, 0, 0, 0), "")
    lock(JOB_LOCK) do
        JOB_STORE[id] = rec
    end
    put!(JOB_QUEUE, id)
    id
end

# ── Worker ────────────────────────────────────────────────────────────────────

function worker(gpu_id::Int)
    # Each worker owns one GPU slot (or -1 for CPU).
    @info "Worker started" gpu_id
    for job_id in JOB_QUEUE
        rec = lock(JOB_LOCK) do
            get(JOB_STORE, job_id, nothing)
        end
        # Job was cancelled before we picked it up.
        rec === nothing && continue

        lock(JOB_LOCK) do
            rec.status = RUNNING
        end

        use_gpu = rec.gpu && gpu_id >= 0 && CUDA_AVAILABLE
        try
            img  = rec.img
            D = rec.D
            if use_gpu
                CUDA.device!(gpu_id)
                img_dev = CUDA.cu(img)
                D_dev   = isnothing(D) ? nothing : CUDA.cu(D)
                sim = TortuositySimulation(img_dev, axis=rec.axis, D=D_dev, gpu=true)
                sol = solve(sim.prob, KrylovJL_CG(), reltol=rec.reltol, verbose=false)
                u_cpu   = Array(sol.u)
                img_cpu = Array(img_dev)
                c   = Array{Float32,3}(vec_to_grid(u_cpu, img_cpu))
                D_cpu = isnothing(D_dev) ? nothing : Array(D_dev)
                tau = Float64(tortuosity(c, axis=rec.axis, D=D_cpu))
            else
                sim = TortuositySimulation(img, axis=rec.axis, D=D, gpu=false)
                sol = solve(sim.prob, KrylovJL_CG(), reltol=rec.reltol, verbose=false)
                c   = Array{Float32,3}(vec_to_grid(sol.u, img))
                tau = Float64(tortuosity(c, axis=rec.axis, D=D))
            end

            lock(JOB_LOCK) do
                rec.tau    = tau
                rec.conc   = c
                release_job_inputs!(rec)
                rec.status = DONE
            end
            @info "Job done" job_id tau gpu=use_gpu

        catch e
            msg = sprint(showerror, e, catch_backtrace())
            @error "Job failed" job_id exception=e
            lock(JOB_LOCK) do
                release_job_inputs!(rec)
                rec.err    = msg
                rec.status = ERROR_STATE
            end
        finally
            maybe_reclaim_memory!(use_gpu)
        end
    end
end

# ── HTTP helpers ──────────────────────────────────────────────────────────────

json_response(status, body::AbstractString) =
    HTTP.Response(status, ["Content-Type" => "application/json"], body=body)

function parse_multipart(req)
    # HTTP.jl multipart parsing
    content_type = HTTP.header(req, "Content-Type", "")
    boundary = match(r"boundary=([^\s;]+)", content_type)
    boundary === nothing && error("No multipart boundary in Content-Type")
    HTTP.parse_multipart_form(req)
end

# ── Routes ────────────────────────────────────────────────────────────────────

const ROUTER = HTTP.Router()

# POST /tortuosity — submit a job
HTTP.register!(ROUTER, "POST", "/tortuosity", function(req)
    try
        parts = parse_multipart(req)
        part_dict = Dict(p.name => p for p in parts)

        # Read image from .npy bytes via a temp file (NPZ.jl requires seekable IO).
        # part.data is a GenericIOBuffer — use read() to extract bytes.
        # Declare img before the try so it is in scope after the finally block.
        img_bytes = read(part_dict["image"].data)
        local img
        let tmp = tempname() * ".npy"
            try
                write(tmp, img_bytes)
                img = convert(Array{Bool}, NPZ.npzread(tmp))
            finally
                isfile(tmp) && rm(tmp)
            end
        end

        # Optional per-voxel diffusivity map
        local D = nothing
        if haskey(part_dict, "D")
            d_bytes = read(part_dict["D"].data)
            let tmp = tempname() * ".npy"
                try
                    write(tmp, d_bytes)
                    D = convert(Array{Float32}, NPZ.npzread(tmp))
                finally
                    isfile(tmp) && rm(tmp)
                end
            end
        end

        axis   = Symbol(strip(String(read(part_dict["axis"].data))))
        reltol = parse(Float32, strip(String(read(part_dict["reltol"].data))))
        gpu    = lowercase(strip(String(read(part_dict["gpu"].data)))) == "true"

        job_id = new_job!(img, D, axis, reltol, gpu)
        @info "Job queued" job_id axis reltol gpu img_size=size(img) has_D=!isnothing(D)
        json_response(202, """{"job_id": "$job_id"}""")
    catch e
        @error "Failed to queue job" exception=e
        json_response(400, """{"error": "$(sprint(showerror, e))"}""")
    end
end)

# GET /job/:id — poll status
HTTP.register!(ROUTER, "GET", "/job/{id}", function(req)
    job_id = HTTP.getparams(req)["id"]
    rec = lock(JOB_LOCK) do
        get(JOB_STORE, job_id, nothing)
    end
    rec === nothing && return json_response(404, """{"error": "unknown job"}""")
    if rec.status == DONE
        json_response(200, """{"status": "done", "tau": $(rec.tau)}""")
    elseif rec.status == ERROR_STATE
        # Escape the error string minimally so JSON stays valid
        escaped = replace(rec.err, "\\" => "\\\\", "\"" => "\\\"", "\n" => "\\n")
        json_response(200, """{"status": "error", "error": "$escaped"}""")
    else
        s = rec.status == RUNNING ? "running" : "pending"
        json_response(200, """{"status": "$s"}""")
    end
end)

# GET /job/:id/conc — download concentration field as .npz
HTTP.register!(ROUTER, "GET", "/job/{id}/conc", function(req)
    job_id = HTTP.getparams(req)["id"]
    rec = lock(JOB_LOCK) do
        candidate = get(JOB_STORE, job_id, nothing)
        if candidate !== nothing && candidate.status == DONE
            delete!(JOB_STORE, job_id)
            return candidate
        end
        nothing
    end
    if rec === nothing
        return json_response(404, """{"error": "not ready"}""")
    end
    # Write .npz to temp file, send bytes, clean up
    tmp = tempname() * ".npz"
    try
        NPZ.npzwrite(tmp, Dict("conc" => rec.conc))
        data = read(tmp)
        HTTP.Response(200, ["Content-Type" => "application/octet-stream"], body=data)
    finally
        release_job_buffers!(rec)
        maybe_reclaim_memory!(rec.gpu)
        isfile(tmp) && rm(tmp)
    end
end)

# DELETE /job/:id — cancel / clean up
HTTP.register!(ROUTER, "DELETE", "/job/{id}", function(req)
    job_id = HTTP.getparams(req)["id"]
    use_gpu = false
    lock(JOB_LOCK) do
        rec = get(JOB_STORE, job_id, nothing)
        if rec !== nothing
            use_gpu = rec.gpu
            release_job_buffers!(rec)
            delete!(JOB_STORE, job_id)
        end
    end
    maybe_reclaim_memory!(use_gpu)
    HTTP.Response(204)
end)

# GET /health
HTTP.register!(ROUTER, "GET", "/health", function(req)
    n_gpus = CUDA_AVAILABLE ? length(collect(CUDA.devices())) : 0
    json_response(200, """{"status": "ok", "gpus": $n_gpus}""")
end)

# ── Warmup & startup ──────────────────────────────────────────────────────────

function warmup()
    @info "Warming up Tortuosity (CPU)..."
    img = trues(6, 6, 6)
    sim = TortuositySimulation(img, axis=:x, gpu=false)
    solve(sim.prob, KrylovJL_CG(), reltol=1f-2, verbose=false)
    @info "CPU warmup complete"
    if CUDA_AVAILABLE
        @info "Warming up Tortuosity (GPU 0)..."
        CUDA.device!(0)
        img_dev = CUDA.cu(img)
        sim = TortuositySimulation(img_dev, axis=:x, gpu=true)
        solve(sim.prob, KrylovJL_CG(), reltol=1f-2, verbose=false)
        @info "GPU warmup complete"
    end
    maybe_reclaim_memory!(CUDA_AVAILABLE)
end

# Spawn one worker task per GPU (or one CPU worker if no GPU available).
gpu_ids = CUDA_AVAILABLE ? collect(0:length(collect(CUDA.devices()))-1) : Int[-1]
for gid in gpu_ids
    @async worker(gid)
end
@info "Worker pool started" workers=length(gpu_ids) gpu_ids

warmup()

const PORT = parse(Int, get(ENV, "JULIA_SERVER_PORT", "2999"))
const HOST = get(ENV, "JULIA_SERVER_HOST", "127.0.0.1")
@info "Julia tortuosity server listening" host=HOST port=PORT
HTTP.serve(ROUTER, HOST, PORT)
