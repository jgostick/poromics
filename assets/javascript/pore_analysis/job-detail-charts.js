'use strict';
import Chart from 'chart.js/auto';

/**
 * Render a pore size distribution bar chart.
 *
 * @param {HTMLCanvasElement} canvas
 * @param {number[]} counts  - histogram counts per bin
 * @param {number[]} binEdges - bin edge values (length = counts.length + 1)
 * @param {number} voxelSize  - voxel size in µm (for axis label context)
 */
function poreSizeHistogram(canvas, counts, binEdges, voxelSize) {
  const labels = counts.map((_, i) => {
    const mid = (binEdges[i] + binEdges[i + 1]) / 2;
    return mid.toFixed(2);
  });

  new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          label: 'Count',
          data: counts,
          backgroundColor: 'rgba(59, 130, 246, 0.6)',
          borderColor: 'rgba(59, 130, 246, 1)',
          borderWidth: 1,
          borderRadius: 2,
          categoryPercentage: 1.0,
          barPercentage: 0.95,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => {
              const i = items[0].dataIndex;
              const lo = binEdges[i].toFixed(2);
              const hi = binEdges[i + 1].toFixed(2);
              return `${lo} – ${hi} µm`;
            },
            label: (item) => `Count: ${item.raw}`,
          },
        },
      },
      scales: {
        x: {
          title: {
            display: true,
            text: 'Pore Diameter (µm)',
          },
          grid: { display: false },
        },
        y: {
          title: {
            display: true,
            text: 'Count',
          },
          beginAtZero: true,
        },
      },
    },
  });
}

export { poreSizeHistogram };

// Expose on the global SiteJS namespace so inline scripts and other bundles can call it.
if (typeof window.SiteJS === 'undefined') {
  window.SiteJS = {};
}
if (!window.SiteJS.PoreAnalysis) {
  window.SiteJS.PoreAnalysis = {};
}
window.SiteJS.PoreAnalysis.poreSizeHistogram = poreSizeHistogram;
