/* global Chart */

const state = {
  config: null,
  data: null,
  range: 'all',         // '4' | '12' | 'all'
  charts: new Map(),    // metric_id -> Chart instance
};

const gridEl = document.getElementById('grid');
const lastUpdatedEl = document.getElementById('last-updated');

// ---------- Load ----------

async function load() {
  try {
    const [configResp, dataResp] = await Promise.all([
      fetch('metrics-config.json'),
      fetch('data.json'),
    ]);
    if (!configResp.ok) throw new Error(`metrics-config.json: ${configResp.status}`);
    if (!dataResp.ok) throw new Error(`data.json: ${dataResp.status}`);
    state.config = await configResp.json();
    state.data = await dataResp.json();
  } catch (err) {
    gridEl.textContent = '';
    const errorBox = document.createElement('div');
    errorBox.className = 'load-error';
    errorBox.textContent = `Failed to load dashboard data: ${err.message}`;
    gridEl.appendChild(errorBox);
    lastUpdatedEl.textContent = '';
    throw err;
  }

  updateLastUpdated();
  render();
  wireRangeSelector();
}

function updateLastUpdated() {
  const ts = state.data.generated_at;
  if (!ts) return;
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) {
    lastUpdatedEl.textContent = `Data: ${ts}`;
    return;
  }
  const fmt = d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit',
    timeZoneName: 'short',
  });
  lastUpdatedEl.textContent = `Data synced ${fmt}`;
}

// ---------- Range ----------

function wireRangeSelector() {
  document.querySelectorAll('.range-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.range = btn.dataset.range;
      render();
    });
  });
}

function weeksForRange() {
  const all = state.data.weeks;
  if (state.range === 'all') return all;
  const n = parseInt(state.range, 10);
  return all.slice(Math.max(0, all.length - n));
}

function seriesForRange(metricId) {
  const all = state.data.series[metricId] || [];
  if (state.range === 'all') return all;
  const n = parseInt(state.range, 10);
  return all.slice(Math.max(0, all.length - n));
}

// ---------- Render ----------

function render() {
  // Destroy existing charts before re-rendering
  state.charts.forEach(c => c.destroy());
  state.charts.clear();
  gridEl.textContent = '';

  for (const metric of state.config.metrics) {
    gridEl.appendChild(renderCard(metric));
  }

  // After DOM is in place, initialize charts
  for (const metric of state.config.metrics) {
    if (metric.status === 'pending_pmf') continue;
    initChart(metric);
  }
}

function renderCard(metric) {
  const card = document.createElement('section');
  card.className = 'card';
  card.setAttribute('data-metric-id', metric.id);

  const series = state.data.series[metric.id] || [];
  const currentValue = lastNumeric(series);

  // --- Header ---
  const header = document.createElement('div');
  header.className = 'card-header';
  const title = document.createElement('h2');
  title.className = 'card-title';
  title.textContent = metric.label;
  const idBadge = document.createElement('span');
  idBadge.className = 'card-id';
  idBadge.textContent = metric.id;
  header.append(title, idBadge);

  // --- Current value ---
  const current = document.createElement('div');
  current.className = 'card-current';
  const currentVal = document.createElement('span');
  currentVal.className = 'card-current-value';
  currentVal.textContent = currentValue === null ? '—' : formatNumber(currentValue);
  current.appendChild(currentVal);
  if (metric.unit) {
    const unit = document.createElement('span');
    unit.className = 'card-current-unit';
    unit.textContent = metric.unit;
    current.appendChild(unit);
  }

  // --- Goal line ---
  const goal = document.createElement('div');
  goal.className = 'card-goal';
  if (metric.goal_value !== null && metric.goal_value !== undefined) {
    const arrow = metric.direction === 'down' ? '↓' : '↑';
    const goalLabel = document.createTextNode('Goal: ');
    const goalValue = document.createElement('span');
    goalValue.className = 'card-goal-value';
    const unitSuffix = metric.unit ? ' ' + metric.unit : '';
    goalValue.textContent = `${arrow} ${formatNumber(metric.goal_value)}${unitSuffix}`;
    goal.append(goalLabel, goalValue);
    if (metric.goal_date) {
      goal.appendChild(document.createTextNode(` by ${formatGoalDate(metric.goal_date)}`));
    }
  } else {
    goal.textContent = 'Goal: TBD';
  }

  // --- Chart area or placeholder ---
  let chartArea;
  if (metric.status === 'pending_pmf') {
    chartArea = document.createElement('div');
    chartArea.className = 'card-placeholder';
    chartArea.textContent = 'Pending PMF';
  } else {
    chartArea = document.createElement('div');
    chartArea.className = 'card-chart-wrap';
    const canvas = document.createElement('canvas');
    canvas.id = `chart-${metric.id}`;
    chartArea.appendChild(canvas);
  }

  // --- Description ---
  const description = document.createElement('div');
  description.className = 'card-description';
  description.textContent = metric.description || '';

  card.append(header, current, goal, chartArea, description);
  return card;
}

function initChart(metric) {
  const canvas = document.getElementById(`chart-${metric.id}`);
  if (!canvas) return;

  const weeks = weeksForRange();
  const values = seriesForRange(metric.id);

  // Goal line: constant value across the full visible range (if numeric goal exists)
  const hasGoal = metric.goal_value !== null && metric.goal_value !== undefined;
  const goalSeries = hasGoal ? weeks.map(() => metric.goal_value) : null;

  const datasets = [
    {
      label: metric.label,
      data: values,
      borderColor: 'rgb(37, 99, 235)',
      backgroundColor: 'rgba(37, 99, 235, 0.08)',
      borderWidth: 2,
      tension: 0.25,
      fill: true,
      pointRadius: 3,
      pointHoverRadius: 5,
      pointBackgroundColor: 'rgb(37, 99, 235)',
      spanGaps: true,
    },
  ];

  if (goalSeries) {
    datasets.push({
      label: 'Goal',
      data: goalSeries,
      borderColor: 'rgb(22, 163, 74)',
      backgroundColor: 'transparent',
      borderWidth: 1.5,
      borderDash: [5, 4],
      pointRadius: 0,
      pointHoverRadius: 0,
      fill: false,
      tension: 0,
    });
  }

  // Y-axis bounds: span at least from 0 (or a bit below min) to a bit above max(data, goal).
  const numericVals = values.filter(v => typeof v === 'number');
  const maxVal = Math.max(
    ...(numericVals.length ? numericVals : [0]),
    hasGoal ? metric.goal_value : -Infinity,
  );
  const minVal = Math.min(
    ...(numericVals.length ? numericVals : [0]),
    hasGoal ? metric.goal_value : Infinity,
  );
  const pad = Math.max(1, (maxVal - minVal) * 0.15);

  const chart = new Chart(canvas, {
    type: 'line',
    data: { labels: weeks, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(26, 26, 26, 0.95)',
          titleFont: { size: 12, weight: '600' },
          bodyFont: { size: 12 },
          padding: 10,
          cornerRadius: 4,
          displayColors: true,
          callbacks: {
            title: (items) => items[0].label,
            label: (ctx) => {
              const v = ctx.parsed.y;
              if (v === null || v === undefined) return `${ctx.dataset.label}: —`;
              return `${ctx.dataset.label}: ${formatNumber(v)}${metric.unit ? ' ' + metric.unit : ''}`;
            },
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: {
            color: '#9a9a96',
            font: { size: 11 },
            maxRotation: 0,
            autoSkipPadding: 16,
            callback: function (value) {
              // Show only MM-DD on x-axis labels
              const label = this.getLabelForValue(value);
              return label && label.length >= 10 ? label.slice(5) : label;
            },
          },
        },
        y: {
          suggestedMin: Math.max(0, Math.floor(minVal - pad)),
          suggestedMax: Math.ceil(maxVal + pad),
          grid: { color: 'rgba(0,0,0,0.04)' },
          ticks: {
            color: '#9a9a96',
            font: { size: 11 },
          },
        },
      },
    },
  });

  state.charts.set(metric.id, chart);
}

// ---------- Helpers ----------

function lastNumeric(arr) {
  for (let i = arr.length - 1; i >= 0; i--) {
    if (typeof arr[i] === 'number') return arr[i];
  }
  return null;
}

function formatNumber(n) {
  if (typeof n !== 'number') return String(n);
  if (Number.isInteger(n)) return n.toLocaleString();
  return n.toLocaleString(undefined, { maximumFractionDigits: 1 });
}

function formatGoalDate(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

load();
