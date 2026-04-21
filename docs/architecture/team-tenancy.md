# Team Tenancy Model

## Core Principle

Most product workflows are team-scoped. Team membership acts as a tenant boundary for data and permissions.

## Core Models

Defined in `apps/teams/models.py`:

- `Team`: tenant boundary and primary collaboration object.
- `Membership`: user-to-team relation with role semantics.
- `Invitation`: pending team invite workflow.
- `BaseTeamModel`: abstract base for team-owned objects.
- `TeamScopedManager` (`for_team`): context-aware manager for automatic team filtering.

## Context Propagation

`apps/teams/context.py` and `apps/teams/middleware.py` provide request/team context propagation.

- Middleware makes the active team available on request objects.
- `for_team` relies on global team context to avoid repetitive explicit filters.

If no team context exists:

- `for_team` returns an empty queryset by default.
- It can raise when strict context mode is enabled (`STRICT_TEAM_CONTEXT`).

## URL and View Conventions

Team URL patterns are mounted under `/a/<team_slug>/...`.

Expected conventions:

- Team views accept `team_slug` as first URL argument.
- Team views should use `@login_and_team_required` or stricter decorators where applicable.
- New team-owned models should inherit from `BaseTeamModel` unless there is a clear exception.

## Async and Task Considerations

For asynchronous execution, do not assume request context exists.

- Pass team/job identifiers explicitly.
- Re-establish context when needed before using `for_team` managers.
- Keep task logic explicit about which team owns side effects.

## Practical Guidance

- Prefer `for_team` for team-scoped query paths in app logic.
- Keep admin/internal maintenance paths explicit when bypassing team context with `objects`.
- Validate all incoming team-scoped access server-side even if UI already constrains choices.
