document.addEventListener('DOMContentLoaded', function () {
  const tooltipTriggerList = Array.prototype.slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
  tooltipTriggerList.forEach(function (tooltipTriggerEl) {
    new bootstrap.Tooltip(tooltipTriggerEl, { html: true })
  })

  const refreshBtn = document.getElementById('forceRefreshBtn')
  if (refreshBtn) {
    refreshBtn.addEventListener('click', function () {
      const spinner = refreshBtn.querySelector('.spinner-border')
      const label = refreshBtn.querySelector('.label')
      if (spinner) spinner.classList.remove('d-none')
      if (label) label.textContent = 'Обновляю…'
      refreshBtn.classList.add('disabled')
    })
  }

  // Mini charts for WB and Ozon (last 14 days)
  async function drawDailyChart(canvasId, mp) {
    const el = document.getElementById(canvasId)
    if (!el || !window.Chart) return
    try {
      const resp = await fetch(`/api/metrics/daily?mp=${encodeURIComponent(mp)}`)
      if (!resp.ok) return
      const data = await resp.json()
      const labels = data.map(d => d.date.slice(5))
      const ordered = data.map(d => d.ordered)
      const purchased = data.map(d => d.purchased)
      const ctx = el.getContext('2d')
      new Chart(ctx, {
        type: 'line',
        data: {
          labels,
          datasets: [
            {
              label: 'Заказано',
              data: ordered,
              borderColor: '#0d6efd',
              backgroundColor: 'rgba(13,110,253,0.1)',
              tension: 0.3,
              pointRadius: 2,
            },
            {
              label: 'Выкуплено',
              data: purchased,
              borderColor: '#198754',
              backgroundColor: 'rgba(25,135,84,0.1)',
              tension: 0.3,
              pointRadius: 2,
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: true, position: 'bottom' } },
          scales: { x: { display: true }, y: { display: true, beginAtZero: true } }
        }
      })
    } catch (e) {}
  }

  drawDailyChart('wbDailyChart', 'wb')
  drawDailyChart('ozonDailyChart', 'ozon')
})


