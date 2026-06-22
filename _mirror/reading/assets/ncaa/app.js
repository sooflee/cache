// --- Loading / error state ---
const loadingOverlay = document.createElement('div');
loadingOverlay.id = 'loading-overlay';
loadingOverlay.innerHTML = `
  <div style="display:flex;flex-direction:column;align-items:center;gap:1.5rem;">
    <div class="spinner"></div>
    <div style="font-family:'IBM Plex Mono',monospace;font-size:0.8rem;color:var(--text-dim);letter-spacing:0.15em;text-transform:uppercase;">Loading data&hellip;</div>
  </div>`;
Object.assign(loadingOverlay.style, {
  position:'fixed',inset:'0',display:'flex',alignItems:'center',justifyContent:'center',
  background:'var(--bg)',zIndex:'9999',transition:'opacity 0.4s',
});
document.body.appendChild(loadingOverlay);

// Spinner CSS
const spinStyle = document.createElement('style');
spinStyle.textContent = `
  .spinner{width:36px;height:36px;border:3px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
  #load-error{text-align:center;padding:3rem 2rem;max-width:500px;margin:0 auto}
  #load-error h3{font-family:'Instrument Serif',serif;font-size:1.5rem;color:var(--red);margin-bottom:1rem}
  #load-error p{font-family:'IBM Plex Mono',monospace;font-size:0.8rem;color:var(--text-dim);line-height:1.6}`;
document.head.appendChild(spinStyle);

// Load data and populate
fetch('./dashboard_data.json')
  .then(r => {
    if (!r.ok) throw new Error(`HTTP ${r.status}: ${r.statusText}`);
    return r.json();
  })
  .then(data => {
    loadingOverlay.style.opacity = '0';
    setTimeout(() => loadingOverlay.remove(), 400);
    render(data);
  })
  .catch(e => {
    console.error('Failed to load data:', e);
    loadingOverlay.innerHTML = `<div id="load-error">
      <h3>Could not load dashboard data</h3>
      <p>${e.message}</p>
      <p style="margin-top:1rem">Generate the data first:<br><code style="color:var(--accent)">python generate_dashboard.py</code></p>
    </div>`;
  });

function render(data) {
  const season = data.season || 2026;
  const models = data.models;
  const seed = models.seedOnly;
  const best = models[data.bestModel] || models.ensemble;

  // Update season references throughout the page
  document.querySelectorAll('.hero-label, .footer, .section h2').forEach(el => {
    el.innerHTML = el.innerHTML.replace(/2026/g, season);
  });
  document.title = `Predicting March Madness ${season}`;

  buildBracket(data);

  // Headline stats — honest framing, lead with log-loss improvement
  const llImprove = ((seed.logloss - best.logloss) / seed.logloss * 100).toFixed(1);
  const brierImprove = ((seed.brier - best.brier) / seed.brier * 100).toFixed(1);

  document.getElementById('accuracy-stats').innerHTML = `
    <div class="stat-card">
      <div class="stat-label">Seed-Only Accuracy</div>
      <div class="stat-value">${seed.accuracy}%</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Our Model Accuracy</div>
      <div class="stat-value">${best.accuracy}%</div>
    </div>
  `;

  document.getElementById('headline-stats').innerHTML = `However, our model reduces log-loss by ${llImprove}% (${seed.logloss}&nbsp;&rarr;&nbsp;${best.logloss}) and Brier score by ${brierImprove}% (${seed.brier}&nbsp;&rarr;&nbsp;${best.brier}) compared to the seed-only baseline. In other words, our model more accurately predicts win probability, especially in later stages of the bracket. Coupled with a Monte Carlo simulation, we more accurately produce a bracket that captures path-dependent effects that seeds alone cannot.`;


  // Feature importance bars
  const featureDescs = {
    AdjEM: 'Adjusted Efficiency Margin: points scored minus points allowed per 100 possessions, adjusted for opponent strength.',
    PreseasonAdjEM: 'Preseason adjusted efficiency margin based on returning talent and recruiting rankings before games are played.',
    AdjEMImprovement: 'How much a team improved their AdjEM from preseason expectations to end of regular season.',
    APFinalVotes: 'Total votes received in the final AP Poll. Captures perceived strength beyond just ranking.',
    RankImprovement: 'Change in computer rankings from preseason to end of season. Rising teams tend to carry momentum.',
    FTRate: 'Free throw rate: free throw attempts as a share of field goal attempts. Teams that get to the line perform better under pressure.',
    AstRate: 'Assist rate: percentage of made baskets that were assisted. Measures offensive cohesion and ball movement.',
    OppThreePtDependence: "How much of the opponent's offense relies on three-pointers. Three-point-heavy teams are more volatile.",
    RecentWinPct: 'Win percentage in the last 10 regular season games. Captures late-season form heading into March.',
    RecentMargin: 'Average margin of victory in recent games. Are they winning comfortably or squeaking by?',
    WinTrendLate: 'Trend in win rate over the final stretch of the season. Peaking or slumping entering the tournament?',
    WorstMargin: "Team's worst loss margin during the season. How bad was their worst day?",
    InjuryRank: 'Composite measure of team health based on player availability and injuries heading into March.',
    ConfDepth: 'Strength-of-schedule proxy: how many tournament-quality teams were in the same conference.',
    ProgramDeepRuns: 'Historical count of Sweet 16+ appearances for the program. Institutional tournament experience.',
    SeedNum: 'NCAA tournament seed number assigned by the selection committee (1 = best, 16 = worst).',
  };
  const maxImp = data.featureImportance[0].importance;
  const impHTML = data.featureImportance.slice(0, 16).map(f => {
    const pct = (f.importance / maxImp * 100).toFixed(0);
    const name = f.feature.replace('_diff', '');
    const colors = {
      AdjEM: 'var(--green)', PreseasonAdjEM: 'var(--green)', AdjEMImprovement: 'var(--green)',
      APFinalVotes: 'var(--accent)', RankImprovement: 'var(--accent)',
      FTRate: 'var(--blue)', AstRate: 'var(--blue)', OppThreePtDependence: 'var(--blue)',
      RecentWinPct: 'var(--purple)', RecentMargin: 'var(--purple)', WinTrendLate: 'var(--purple)',
      WorstMargin: 'var(--green)', InjuryRank: 'var(--green)',
      ConfDepth: 'var(--blue)', ProgramDeepRuns: 'var(--blue)',
    };
    const color = colors[name] || 'var(--purple)';
    const desc = featureDescs[name] || '';
    const tooltip = desc ? `<div class="bar-tooltip">${desc}</div>` : '';
    return `<div class="bar-row">
      <div class="bar-label">${name}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:${color}"><span>${f.importance.toFixed(3)}</span></div></div>
      ${tooltip}
    </div>`;
  }).join('');
  document.getElementById('importance-chart').innerHTML = impHTML;

  // Model comparison table
  const modelOrder = ['seedOnly', 'logistic', 'xgboost', 'ensemble'];
  const availableModels = modelOrder.filter(k => models[k]);
  const bestLL = Math.min(...availableModels.map(k => models[k].logloss));
  const bestAcc = Math.max(...availableModels.map(k => models[k].accuracy));
  const bestBrier = Math.min(...availableModels.map(k => models[k].brier));

  const tbody = availableModels.map(k => {
    const m = models[k];
    const isWinner = m.logloss === bestLL;
    return `<tr class="${isWinner ? 'winner' : ''}">
      <td class="model-name">${m.name}</td>
      <td class="${m.accuracy === bestAcc ? 'best' : ''}">${m.accuracy}%</td>
      <td class="${m.logloss === bestLL ? 'best' : ''}">${m.logloss}</td>
      <td class="${m.brier === bestBrier ? 'best' : ''}">${m.brier}</td>
    </tr>`;
  }).join('');
  var modelTbody = document.getElementById('model-tbody');
  if (modelTbody) modelTbody.innerHTML = tbody;

  // Season-by-season chart
  const ensSeasons = best.perSeason;
  const seedSeasons = seed.perSeason;
  const maxAcc = 0.85;
  const minAcc = 0.30;

  const barsHTML = ensSeasons.map((s, i) => {
    const seedAcc = seedSeasons[i] ? seedSeasons[i].accuracy : 0.5;
    const modelAcc = s.accuracy;
    const seedH = ((seedAcc - minAcc) / (maxAcc - minAcc) * 100).toFixed(0);
    const modelH = ((modelAcc - minAcc) / (maxAcc - minAcc) * 100).toFixed(0);
    return `<div class="chart-bar-group">
      <div style="display:flex;gap:2px;align-items:flex-end;width:100%;height:100%">
        <div class="chart-bar seed" style="height:${seedH}%;flex:1" title="Seed: ${(seedAcc*100).toFixed(0)}%"></div>
        <div class="chart-bar model" style="height:${modelH}%;flex:1" title="Model: ${(modelAcc*100).toFixed(0)}%"></div>
      </div>
      <div class="chart-bar-label">'${String(s.season).slice(2)}</div>
    </div>`;
  }).join('');
  document.getElementById('season-bars').innerHTML = barsHTML;

  // Team table
  const teamHTML = data.teamProbabilities.slice(0, 30).map(t => {
    const seedT = data.seedBaseline.find(s => s.id === t.id);
    const seedChamp = seedT ? seedT.champ : 0;
    const delta = (t.champ - seedChamp).toFixed(1);
    const deltaClass = delta > 0 ? 'delta-pos' : delta < 0 ? 'delta-neg' : '';
    const deltaStr = delta > 0 ? `+${delta}` : delta;

    const probClass = v => v >= 10 ? 'prob-high' : v >= 2 ? 'prob-med' : 'prob-low';

    return `<tr>
      <td>${t.name}</td>
      <td>${t.seed}</td>
      <td class="${probClass(t.r64)}">${t.r64}</td>
      <td class="${probClass(t.r32)}">${t.r32}</td>
      <td class="${probClass(t.s16)}">${t.s16}</td>
      <td class="${probClass(t.e8)}">${t.e8}</td>
      <td class="${probClass(t.f4)}">${t.f4}</td>
      <td class="${probClass(t.champ)}">${t.champ}%</td>
      <td class="${deltaClass}">${deltaStr}%</td>
    </tr>`;
  }).join('');
  document.getElementById('team-tbody').innerHTML = teamHTML;

  // --- Interactive predictor (pairwise lookup) ---
  if (data.predictorModel) {
    var pm = data.predictorModel;
    var teamNamesList = Object.keys(pm.teamValues).sort();
    var selectedA = '', selectedB = '';

    var predDisplayNames = {
      AdjEM: 'Adj. Efficiency', RecentWinPct: 'Recent Win %', AstRate: 'Assist Rate',
      RecentMargin: 'Recent Margin', FTRate: 'Free Throw Rate',
      OppThreePtDependence: 'Opp 3PT Dep.', WorstMargin: 'Worst Margin',
      ProgramDeepRuns: 'Deep Runs', WinTrendLate: 'Win Trend',
      ConfDepth: 'Conf Depth', InjuryRank: 'Injury Rank',
      APFinalVotes: 'AP Votes', AdjEMImprovement: 'EM Improvement',
      RankImprovement: 'Rank Improv.', PreseasonAdjEM: 'Preseason EM',
      SeedNum: 'Seed',
    };

    function fmtFeatVal(v) {
      if (v == null) return '—';
      if (Math.abs(v) >= 100) return Math.round(v).toString();
      if (Math.abs(v) >= 10) return v.toFixed(1);
      return v.toFixed(2);
    }

    function showFeatures(name, containerId) {
      var el = document.getElementById(containerId);
      if (!name || !pm.teamValues[name]) { el.innerHTML = ''; return; }
      var vals = pm.teamValues[name];
      var html = '';
      for (var i = 0; i < pm.features.length; i++) {
        var feat = pm.features[i];
        var display = predDisplayNames[feat] || feat;
        var v = vals[feat];
        html += '<div class="pred-feat-row">' +
          '<span class="pred-feat-name">' + display + '</span>' +
          '<span class="pred-feat-val">' + fmtFeatVal(v) + '</span>' +
          '</div>';
      }
      el.innerHTML = html;
    }

    function lookupProb() {
      if (!selectedA || !selectedB || selectedA === selectedB) {
        document.getElementById('pred-bar-fill').style.width = '50%';
        document.getElementById('pred-pct-a').textContent = '—';
        document.getElementById('pred-pct-b').textContent = '—';
        return;
      }
      // Pairwise keys are stored as "lowerName|higherName" by team ID order,
      // but we stored by name in generate_dashboard. Try both orderings.
      var key1 = selectedA + '|' + selectedB;
      var key2 = selectedB + '|' + selectedA;
      var prob;
      if (pm.pairwise[key1] != null) {
        prob = pm.pairwise[key1];
      } else if (pm.pairwise[key2] != null) {
        prob = 1 - pm.pairwise[key2];
      } else {
        prob = 0.5;
      }
      var pctA = (prob * 100).toFixed(1);
      var pctB = ((1 - prob) * 100).toFixed(1);
      document.getElementById('pred-bar-fill').style.width = pctA + '%';
      document.getElementById('pred-pct-a').textContent = pctA + '%';
      document.getElementById('pred-pct-b').textContent = pctB + '%';
    }

    // Populate team dropdowns sorted by seed
    var teamSeeds = {};
    var teamSeedNums = {};
    data.teamProbabilities.forEach(function(t) { teamSeeds[t.name] = t.seed; teamSeedNums[t.name] = t.seedNum; });

    teamNamesList.sort(function(a, b) {
      var sa = teamSeedNums[a] || 99, sb = teamSeedNums[b] || 99;
      return sa !== sb ? sa - sb : a.localeCompare(b);
    });

    var optHTML = '<option value="">Select a team...</option>';
    for (var i = 0; i < teamNamesList.length; i++) {
      var tn = teamNamesList[i];
      var seedLabel = teamSeeds[tn] ? teamSeeds[tn] + ' ' : '';
      optHTML += '<option value="' + tn + '">' + seedLabel + tn + '</option>';
    }
    document.getElementById('pred-select-a').innerHTML = optHTML;
    document.getElementById('pred-select-b').innerHTML = optHTML;

    function selectTeam(name, side) {
      if (side === 'a') selectedA = name;
      else selectedB = name;
      document.getElementById('pred-name-' + side).textContent = name || ('Team ' + side.toUpperCase());
      showFeatures(name, 'pred-features-' + side);
      lookupProb();
    }

    document.getElementById('pred-select-a').addEventListener('change', function() { selectTeam(this.value, 'a'); });
    document.getElementById('pred-select-b').addEventListener('change', function() { selectTeam(this.value, 'b'); });

    // Default selections
    document.getElementById('pred-select-a').value = 'Duke';
    selectTeam('Duke', 'a');
    document.getElementById('pred-select-b').value = 'Michigan';
    selectTeam('Michigan', 'b');
  }
}

// Scroll reveal
const observer = new IntersectionObserver(entries => {
  entries.forEach(e => {
    if (e.isIntersecting) {
      e.target.classList.add('visible');

      // Trigger sim counter animation
      const counter = e.target.querySelector('#sim-counter');
      if (counter && !counter.dataset.animated) {
        counter.dataset.animated = 'true';
        animateCounter(counter, 0, 50000, 2000);
      }
    }
  });
}, { threshold: 0.1 });

document.querySelectorAll('.reveal').forEach(el => observer.observe(el));

// Counter animation
function animateCounter(el, start, end, duration) {
  const startTime = performance.now();
  function update(now) {
    const elapsed = now - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    const value = Math.floor(start + (end - start) * eased);
    el.textContent = value.toLocaleString();
    if (progress < 1) requestAnimationFrame(update);
  }
  requestAnimationFrame(update);
}

// --- Interactive bracket with click-to-upset ---
var _bracketTeams = null;
var _originalTeams = null;  // unmodified copy for re-adjustment
var _bracketOverrides = {};
var _bracketProbMode = 'total'; // 'normalized' or 'total'
var _bracketListenersSet = false;
var _completedGames = {};    // populated from ESPN
var _playinResults = {};     // populated from ESPN
var _predictions = {};       // gameId → predicted winner index
var _pairwise = null;
var _refreshTimer = null;
var _bracketSeason = 2026;

// ESPN API → our bracket mapping
var _espnRegionMap = { 'East': 'W', 'South': 'X', 'Midwest': 'Y', 'West': 'Z' };
var _seedOrder = [1, 16, 8, 9, 5, 12, 4, 13, 6, 11, 3, 14, 7, 10, 2, 15];
var _seedPos = {};
_seedOrder.forEach(function(s, i) { _seedPos[s] = i; });
var _espnRoundMap = { '1st Round': 0, '2nd Round': 1, 'Sweet 16': 2, 'Elite Eight': 3, 'Regional Final': 3 };
var _espnNameMap = {
  'Ohio State': 'Ohio St', 'Michigan State': 'Michigan St', 'Iowa State': 'Iowa St',
  'Utah State': 'Utah St', 'North Dakota State': 'N Dakota St', 'Miami (OH)': 'Miami OH',
  'Miami (FL)': 'Miami FL', 'Prairie View A&M': 'Prairie View', "St. John's (NY)": "St John's",
  "Saint John's": "St John's", "St. John's": "St John's", 'St. Louis': 'St Louis',
  "Saint Mary's": "St Mary's CA", "St. Mary's": "St Mary's CA", "St. Mary's (CA)": "St Mary's CA",
  'Tennessee State': 'Tennessee St', 'McNeese State': 'McNeese St', 'McNeese': 'McNeese St',
  'Wright State': 'Wright St', 'Queens (NC)': 'Queens NC', 'Queens': 'Queens NC',
  'LIU': 'LIU Brooklyn', 'Northern Iowa': 'Northern Iowa', 'Cal Baptist': 'Cal Baptist',
  'South Florida': 'South Florida', 'NC State': 'NC State', 'North Carolina State': 'NC State',
  "Hawai'i": 'Hawaii', "Hawai\u02BBi": 'Hawaii', 'Hawaii': 'Hawaii',
  'Kennesaw St': 'Kennesaw', 'Kennesaw State': 'Kennesaw',
  'Saint Mary\'s (CA)': "St Mary's CA", 'North Carolina': 'North Carolina',
  'Prairie View': 'Prairie View', 'Miami OH': 'Miami OH',
};

function clearDownstream(gameId) {
  if (gameId === 'champ') return;
  var parts = gameId.split('-');
  if (parts[0] === 'f4') {
    delete _bracketOverrides['champ'];
    return;
  }
  var prefix = parts[0];
  var round = parseInt(parts[1]);
  var game = parseInt(parts[2]);
  var g = game;
  for (var r = round + 1; r <= 3; r++) {
    g = Math.floor(g / 2);
    delete _bracketOverrides[prefix + '-' + r + '-' + g];
  }
  if (prefix === 'W' || prefix === 'X') {
    delete _bracketOverrides['f4-0'];
  } else {
    delete _bracketOverrides['f4-1'];
  }
  delete _bracketOverrides['champ'];
}

function computePredictions() {
  _predictions = {};
  var roundKeys = ['r64', 'r32', 's16', 'e8'];
  var regionWinners = {};

  ['W', 'X', 'Y', 'Z'].forEach(function(prefix) {
    // Use _originalTeams (pre-adjustment) so predictions reflect the model, not results
    var teams = _seedOrder.map(function(s) {
      var cands = _originalTeams.filter(function(t) {
        return t.seed.charAt(0) === prefix && t.seedNum === s;
      });
      if (!cands.length) return null;
      // For play-in slots: model picks the team with higher r64
      return cands.reduce(function(a, b) { return a.r64 > b.r64 ? a : b; });
    });

    var slots = teams;
    for (var round = 0; round <= 3; round++) {
      var nextSlots = [];
      for (var i = 0; i < slots.length; i += 2) {
        var a = slots[i], b = slots[i + 1];
        var gid = prefix + '-' + round + '-' + Math.floor(i / 2);
        if (a && b) {
          var pred = a[roundKeys[round]] >= b[roundKeys[round]] ? 0 : 1;
          _predictions[gid] = pred;
          nextSlots.push(pred === 0 ? a : b);
        } else {
          nextSlots.push(a || b);
        }
      }
      slots = nextSlots;
    }
    regionWinners[prefix] = slots[0];
  });

  // Final Four predictions
  var f4pairs = [['f4-0', 'W', 'X'], ['f4-1', 'Y', 'Z']];
  var f4Winners = [];
  f4pairs.forEach(function(cfg) {
    var a = regionWinners[cfg[1]], b = regionWinners[cfg[2]];
    if (a && b) {
      var pred = a.f4 >= b.f4 ? 0 : 1;
      _predictions[cfg[0]] = pred;
      f4Winners.push(pred === 0 ? a : b);
    } else {
      f4Winners.push(a || b);
    }
  });

  // Championship prediction
  if (f4Winners[0] && f4Winners[1]) {
    _predictions['champ'] = f4Winners[0].champ >= f4Winners[1].champ ? 0 : 1;
  }
}

function resolveTeam(prefix, seedNum) {
  var cands = _bracketTeams.filter(function(t) {
    return t.seed.charAt(0) === prefix && t.seedNum === seedNum;
  });
  if (!cands.length) return null;
  if (cands.length === 1) return cands[0];
  var pk = prefix + seedNum;
  if (_playinResults[pk]) {
    var w = cands.find(function(t) { return t.name === _playinResults[pk]; });
    if (w) return w;
  }
  return cands.reduce(function(a, b) { return a.r64 > b.r64 ? a : b; });
}

function conditionOnWin(winner, loser, roundKey) {
  var roundKeys = ['r64', 'r32', 's16', 'e8', 'f4', 'champ'];
  var idx = roundKeys.indexOf(roundKey);
  var orig = winner[roundKey];
  if (orig > 0) {
    var scale = 100 / orig;
    winner[roundKey] = 100;
    for (var i = idx + 1; i < roundKeys.length; i++)
      winner[roundKeys[i]] = Math.min(winner[roundKeys[i]] * scale, 100);
  } else {
    winner[roundKey] = 100;
  }
  for (var i = idx; i < roundKeys.length; i++) loser[roundKeys[i]] = 0;
}

function adjustForResults() {
  var roundKeys = ['r64', 'r32', 's16', 'e8', 'f4', 'champ'];

  // 1. Adjust play-in team probabilities
  Object.keys(_playinResults).forEach(function(key) {
    var prefix = key.charAt(0);
    var seedNum = parseInt(key.substring(1));
    var winnerName = _playinResults[key];
    var cands = _bracketTeams.filter(function(t) {
      return t.seed.charAt(0) === prefix && t.seedNum === seedNum;
    });
    if (cands.length < 2) return;
    var winner = cands.find(function(t) { return t.name === winnerName; });
    var loser = cands.find(function(t) { return t.name !== winnerName; });
    if (!winner || !loser) return;
    var pKey1 = winner.name + '|' + loser.name;
    var pKey2 = loser.name + '|' + winner.name;
    var pWin = 0.5;
    if (_pairwise[pKey1] !== undefined) pWin = _pairwise[pKey1];
    else if (_pairwise[pKey2] !== undefined) pWin = 1 - _pairwise[pKey2];
    if (pWin > 0) {
      var scale = 1 / pWin;
      roundKeys.forEach(function(k) { winner[k] = Math.min(winner[k] * scale, 100); });
    }
    roundKeys.forEach(function(k) { loser[k] = 0; });
  });

  // 2. Process completed games region by region, round by round
  ['W', 'X', 'Y', 'Z'].forEach(function(prefix) {
    var teams = _seedOrder.map(function(s) { return resolveTeam(prefix, s); });
    var slots = teams;
    for (var round = 0; round <= 3; round++) {
      var nextSlots = [];
      for (var i = 0; i < slots.length; i += 2) {
        var a = slots[i], b = slots[i + 1];
        var gid = prefix + '-' + round + '-' + Math.floor(i / 2);
        var completed = _completedGames[gid];
        if (completed && a && b) {
          var winner = completed.w === 0 ? a : b;
          var loser = completed.w === 0 ? b : a;
          conditionOnWin(winner, loser, roundKeys[round]);
          nextSlots.push(winner);
        } else {
          var rk = roundKeys[round];
          var pred = (a && b) ? (a[rk] >= b[rk] ? a : b) : (a || b);
          nextSlots.push(pred);
        }
      }
      slots = nextSlots;
    }
  });

  // 3. Final Four & Championship
  // (Region winners aren't tracked here — handled in renderBracket)
}

function rebuildFromResults() {
  _bracketTeams = _originalTeams.map(function(t) { return Object.assign({}, t); });
  computePredictions();
  adjustForResults();
  renderBracket();
}

function buildBracket(data) {
  _bracketSeason = data.season || 2026;
  _pairwise = data.predictorModel.pairwise;
  _originalTeams = data.teamProbabilities;
  _bracketTeams = _originalTeams.map(function(t) { return Object.assign({}, t); });
  computePredictions();
  _bracketOverrides = {};

  var container = document.getElementById('bracket-container');
  if (!_bracketListenersSet) {
    var _suppressHover = false;
    container.addEventListener('click', function(e) {
      var el = e.target.closest('.b-team');
      if (!el) return;
      var gameId = el.dataset.game;
      if (_completedGames[gameId]) return; // Cannot change finished games
      var idx = parseInt(el.dataset.idx);
      if (el.classList.contains('winner')) {
        if (_bracketOverrides[gameId] === undefined) return;
        delete _bracketOverrides[gameId];
      } else {
        _bracketOverrides[gameId] = idx;
      }
      clearDownstream(gameId);
      _suppressHover = true;
      renderBracket();
      setTimeout(function() { _suppressHover = false; }, 50);
    });
    container.addEventListener('mouseover', function(e) {
      if (_suppressHover) return;
      var el = e.target.closest('.b-team');
      if (!el) return;
      var name = el.dataset.team;
      var bracket = container.querySelector('.bracket');
      if (!bracket || !name) return;
      bracket.classList.add('has-hover');
      bracket.querySelectorAll('.b-team[data-team="' + name + '"]').forEach(function(t) { t.classList.add('path-active'); });
    });
    container.addEventListener('mouseout', function(e) {
      var el = e.target.closest('.b-team');
      if (!el) return;
      var bracket = container.querySelector('.bracket');
      if (!bracket) return;
      bracket.classList.remove('has-hover');
      bracket.querySelectorAll('.path-active').forEach(function(t) { t.classList.remove('path-active'); });
    });
    var _probDescs = {
      normalized: 'Win % — Probability of winning each matchup, normalized so both teams sum to 100%.',
      total: "Advance % — Each team's overall probability of advancing to that round from 50K simulations."
    };
    document.getElementById('prob-toggle').addEventListener('click', function(e) {
      var btn = e.target.closest('.prob-btn');
      if (!btn || btn.classList.contains('active')) return;
      _bracketProbMode = btn.dataset.mode;
      document.querySelectorAll('.prob-btn').forEach(function(b) { b.classList.remove('active'); });
      btn.classList.add('active');
      document.getElementById('prob-desc').textContent = _probDescs[_bracketProbMode];
      renderBracket();
    });

    _bracketListenersSet = true;
  }
  renderBracket();
  fetchTournamentResults();
  if (!_refreshTimer) _refreshTimer = setInterval(fetchTournamentResults, 5 * 60 * 1000);
}

function renderBracket() {
  var teams = _bracketTeams;
  var seedOrder = [1, 16, 8, 9, 5, 12, 4, 13, 6, 11, 3, 14, 7, 10, 2, 15];
  var roundKeys = ['r64', 'r32', 's16', 'e8'];
  var overrides = _bracketOverrides;

  function getRegionTeams(prefix) {
    return seedOrder.map(function(s) {
      var cands = teams.filter(function(t) { return t.seed.charAt(0) === prefix && t.seedNum === s; });
      if (!cands.length) return { name: 'TBD', seedNum: s, r64: 0, r32: 0, s16: 0, e8: 0, f4: 0, champ: 0 };
      if (cands.length > 1) {
        var pk = prefix + s;
        if (_playinResults[pk]) {
          var w = cands.find(function(t) { return t.name === _playinResults[pk]; });
          if (w) return w;
        }
      }
      return cands.reduce(function(a, b) { return a.r64 > b.r64 ? a : b; });
    });
  }

  function simRegion(prefix) {
    var t = getRegionTeams(prefix);
    var r64 = [];
    for (var i = 0; i < 16; i += 2) {
      var gid = prefix + '-0-' + (i / 2);
      var completed = _completedGames[gid];
      var ov = overrides[gid];
      var modelPred = t[i].r64 >= t[i + 1].r64 ? 0 : 1;
      var w;
      if (completed) {
        w = completed.w;
      } else {
        w = (ov !== undefined) ? ov : modelPred;
      }
      r64.push({ t: [t[i], t[i + 1]], w: w, id: gid,
        upset: !completed && ov !== undefined && ov !== modelPred,
        completed: !!completed, score: completed ? completed.s : null,
        correct: completed ? (_predictions[gid] === completed.w) : null });
    }
    var r32 = [];
    for (var i = 0; i < 8; i += 2) {
      var a = r64[i].t[r64[i].w], b = r64[i + 1].t[r64[i + 1].w];
      var gid = prefix + '-1-' + (i / 2);
      var cg = _completedGames[gid], ov = overrides[gid];
      var mp = a.r32 >= b.r32 ? 0 : 1;
      var w = cg ? cg.w : (ov !== undefined) ? ov : mp;
      r32.push({ t: [a, b], w: w, id: gid, upset: !cg && ov !== undefined && ov !== mp,
        completed: !!cg, score: cg ? cg.s : null,
        correct: cg ? (_predictions[gid] === cg.w) : null });
    }
    var s16 = [];
    for (var i = 0; i < 4; i += 2) {
      var a = r32[i].t[r32[i].w], b = r32[i + 1].t[r32[i + 1].w];
      var gid = prefix + '-2-' + (i / 2);
      var cg = _completedGames[gid], ov = overrides[gid];
      var mp = a.s16 >= b.s16 ? 0 : 1;
      var w = cg ? cg.w : (ov !== undefined) ? ov : mp;
      s16.push({ t: [a, b], w: w, id: gid, upset: !cg && ov !== undefined && ov !== mp,
        completed: !!cg, score: cg ? cg.s : null,
        correct: cg ? (_predictions[gid] === cg.w) : null });
    }
    var a = s16[0].t[s16[0].w], b = s16[1].t[s16[1].w];
    var gid = prefix + '-3-0';
    var cg = _completedGames[gid], ov = overrides[gid];
    var mp = a.e8 >= b.e8 ? 0 : 1;
    var w = cg ? cg.w : (ov !== undefined) ? ov : mp;
    var e8 = [{ t: [a, b], w: w, id: gid, upset: !cg && ov !== undefined && ov !== mp,
      completed: !!cg, score: cg ? cg.s : null,
      correct: cg ? (_predictions[gid] === cg.w) : null }];
    return { rounds: [r64, r32, s16, e8], winner: e8[0].t[e8[0].w] };
  }

  function teamEl(team, isW, prob, gameId, teamIdx, isUpset, isCompleted, completedScore, isCorrect) {
    var probStr;
    if (isCompleted && completedScore) {
      probStr = completedScore;
    } else {
      probStr = prob >= 1 ? Math.round(prob) + '%' : prob.toFixed(1) + '%';
    }
    var cls = 'b-team';
    if (isCompleted) cls += ' completed';
    if (isW) cls += ' winner';
    if (isW && isUpset) cls += ' upset';
    if (isCompleted && isW) cls += isCorrect ? ' correct' : ' wrong';
    return '<div class="' + cls + '" data-team="' + team.name + '" data-game="' + gameId + '" data-idx="' + teamIdx + '">' +
      '<span class="b-seed">' + team.seedNum + '</span>' +
      '<span class="b-name">' + team.name + '</span>' +
      '<span class="b-prob">' + probStr + '</span></div>';
  }

  function renderRound(games, roundKey) {
    var h = '<div class="bracket-round">';
    for (var i = 0; i < games.length; i += 2) {
      h += '<div class="b-pair">';
      for (var j = i; j < Math.min(i + 2, games.length); j++) {
        var g = games[j];
        var rawA = g.t[0][roundKey], rawB = g.t[1][roundKey];
        var probA, probB;
        if (_bracketProbMode === 'total') {
          probA = rawA;
          probB = rawB;
        } else {
          var total = rawA + rawB || 1;
          probA = rawA / total * 100;
          probB = rawB / total * 100;
        }
        var scoreA = null, scoreB = null;
        if (g.completed && g.score) {
          scoreA = g.score[0] + '-' + g.score[1];
          scoreB = g.score[1] + '-' + g.score[0];
        }
        h += '<div class="b-game">' +
          teamEl(g.t[0], g.w === 0, probA, g.id, 0, g.upset && g.w === 0, g.completed, scoreA, g.correct) +
          teamEl(g.t[1], g.w === 1, probB, g.id, 1, g.upset && g.w === 1, g.completed, scoreB, g.correct) +
          '</div>';
      }
      h += '</div>';
    }
    return h + '</div>';
  }

  function renderRegion(prefix, isRight) {
    var s = simRegion(prefix);
    var html = '<div class="bracket-region">';
    if (isRight) {
      for (var i = s.rounds.length - 1; i >= 0; i--) html += renderRound(s.rounds[i], roundKeys[i]);
    } else {
      for (var i = 0; i < s.rounds.length; i++) html += renderRound(s.rounds[i], roundKeys[i]);
    }
    html += '</div>';
    return { html: html, winner: s.winner };
  }

  var W = renderRegion('W', false);
  var X = renderRegion('X', false);
  var Y = renderRegion('Y', true);
  var Z = renderRegion('Z', true);

  // Final Four
  var f4Lcg = _completedGames['f4-0'], f4LOv = overrides['f4-0'];
  var f4L = { t: [W.winner, X.winner], id: 'f4-0' };
  var f4Lmp = f4L.t[0].f4 >= f4L.t[1].f4 ? 0 : 1;
  f4L.w = f4Lcg ? f4Lcg.w : (f4LOv !== undefined) ? f4LOv : f4Lmp;
  f4L.upset = !f4Lcg && f4LOv !== undefined && f4LOv !== f4Lmp;
  f4L.completed = !!f4Lcg; f4L.score = f4Lcg ? f4Lcg.s : null;
  f4L.correct = f4Lcg ? (_predictions['f4-0'] === f4Lcg.w) : null;

  var f4Rcg = _completedGames['f4-1'], f4ROv = overrides['f4-1'];
  var f4R = { t: [Y.winner, Z.winner], id: 'f4-1' };
  var f4Rmp = f4R.t[0].f4 >= f4R.t[1].f4 ? 0 : 1;
  f4R.w = f4Rcg ? f4Rcg.w : (f4ROv !== undefined) ? f4ROv : f4Rmp;
  f4R.upset = !f4Rcg && f4ROv !== undefined && f4ROv !== f4Rmp;
  f4R.completed = !!f4Rcg; f4R.score = f4Rcg ? f4Rcg.s : null;
  f4R.correct = f4Rcg ? (_predictions['f4-1'] === f4Rcg.w) : null;

  var champL = f4L.t[f4L.w], champR = f4R.t[f4R.w];
  var ccg = _completedGames['champ'], champOv = overrides['champ'];
  var champGame = { t: [champL, champR], id: 'champ' };
  var champMp = champL.champ >= champR.champ ? 0 : 1;
  champGame.w = ccg ? ccg.w : (champOv !== undefined) ? champOv : champMp;
  champGame.upset = !ccg && champOv !== undefined && champOv !== champMp;
  champGame.completed = !!ccg; champGame.score = ccg ? ccg.s : null;
  champGame.correct = ccg ? (_predictions['champ'] === ccg.w) : null;
  var champ = champGame.t[champGame.w];

  var container = document.getElementById('bracket-container');
  container.innerHTML =
    '<div class="bracket">' +
      '<div class="bracket-side left">' + W.html + X.html + '</div>' +
      '<div class="bracket-center">' +
        '<div class="bracket-f4-half">' +
          '<div class="bracket-f4-label">FINAL FOUR</div>' +
          (function() {
            var pA, pB;
            if (_bracketProbMode === 'total') {
              pA = f4L.t[0].f4; pB = f4L.t[1].f4;
            } else {
              var tL = f4L.t[0].f4 + f4L.t[1].f4 || 1;
              pA = f4L.t[0].f4 / tL * 100; pB = f4L.t[1].f4 / tL * 100;
            }
            var sLA = null, sLB = null;
            if (f4L.completed && f4L.score) { sLA = f4L.score[0]+'-'+f4L.score[1]; sLB = f4L.score[1]+'-'+f4L.score[0]; }
            return '<div class="b-game">' +
              teamEl(f4L.t[0], f4L.w === 0, pA, 'f4-0', 0, f4L.upset && f4L.w === 0, f4L.completed, sLA, f4L.correct) +
              teamEl(f4L.t[1], f4L.w === 1, pB, 'f4-0', 1, f4L.upset && f4L.w === 1, f4L.completed, sLB, f4L.correct) +
              '</div>';
          })() +
        '</div>' +
        '<div class="bracket-champ">' +
          '<div class="bracket-champ-label">CHAMPIONSHIP</div>' +
          (function() {
            var pA, pB;
            if (_bracketProbMode === 'total') {
              pA = champGame.t[0].champ; pB = champGame.t[1].champ;
            } else {
              var tC = champGame.t[0].champ + champGame.t[1].champ || 1;
              pA = champGame.t[0].champ / tC * 100; pB = champGame.t[1].champ / tC * 100;
            }
            var sCA = null, sCB = null;
            if (champGame.completed && champGame.score) { sCA = champGame.score[0]+'-'+champGame.score[1]; sCB = champGame.score[1]+'-'+champGame.score[0]; }
            return '<div class="b-game">' +
              teamEl(champGame.t[0], champGame.w === 0, pA, 'champ', 0, champGame.upset && champGame.w === 0, champGame.completed, sCA, champGame.correct) +
              teamEl(champGame.t[1], champGame.w === 1, pB, 'champ', 1, champGame.upset && champGame.w === 1, champGame.completed, sCB, champGame.correct) +
              '</div>';
          })() +
          '<div class="bracket-champ-team">' + champ.name + '</div>' +
        '</div>' +
        '<div class="bracket-f4-half">' +
          (function() {
            var pA, pB;
            if (_bracketProbMode === 'total') {
              pA = f4R.t[0].f4; pB = f4R.t[1].f4;
            } else {
              var tR = f4R.t[0].f4 + f4R.t[1].f4 || 1;
              pA = f4R.t[0].f4 / tR * 100; pB = f4R.t[1].f4 / tR * 100;
            }
            var sRA = null, sRB = null;
            if (f4R.completed && f4R.score) { sRA = f4R.score[0]+'-'+f4R.score[1]; sRB = f4R.score[1]+'-'+f4R.score[0]; }
            return '<div class="b-game">' +
              teamEl(f4R.t[0], f4R.w === 0, pA, 'f4-1', 0, f4R.upset && f4R.w === 0, f4R.completed, sRA, f4R.correct) +
              teamEl(f4R.t[1], f4R.w === 1, pB, 'f4-1', 1, f4R.upset && f4R.w === 1, f4R.completed, sRB, f4R.correct) +
              '</div>';
          })() +
        '</div>' +
      '</div>' +
      '<div class="bracket-side right">' + Y.html + Z.html + '</div>' +
    '</div>';
}

// --- Live results from ESPN ---
function espnToOurName(espnName) {
  return _espnNameMap[espnName] || espnName;
}

function matchPlayinWinner(espnName, candidates) {
  var mapped = espnToOurName(espnName);
  var exact = candidates.find(function(c) { return c.name === mapped; });
  if (exact) return exact;
  var lower = mapped.toLowerCase();
  var ci = candidates.find(function(c) { return c.name.toLowerCase() === lower; });
  if (ci) return ci;
  var sub = candidates.find(function(c) {
    var cn = c.name.toLowerCase();
    return lower.indexOf(cn) !== -1 || cn.indexOf(lower) !== -1;
  });
  return sub || candidates[0];
}

function processEspnGame(event) {
  var comp = event.competitions[0];
  if (!comp || !comp.status || !comp.status.type.completed) return;
  var note = (comp.notes && comp.notes[0]) ? comp.notes[0].headline : '';
  var regionMatch = note.match(/(East|South|Midwest|West)\s+Region/);

  var teams = comp.competitors;
  var winner = teams.find(function(t) { return t.winner; });
  var loser = teams.find(function(t) { return !t.winner; });
  if (!winner || !loser) return;
  var wSeed = winner.curatedRank ? winner.curatedRank.current : null;
  var lSeed = loser.curatedRank ? loser.curatedRank.current : null;
  var wScore = parseInt(winner.score);
  var lScore = parseInt(loser.score);
  var wName = winner.team.shortDisplayName;

  // Play-in (First Four)
  if (note.indexOf('First Four') !== -1) {
    if (!regionMatch) return;
    var prefix = _espnRegionMap[regionMatch[1]];
    var seedNum = wSeed || lSeed;
    if (!prefix || !seedNum) return;
    var pk = prefix + seedNum;
    var cands = _originalTeams.filter(function(t) {
      return t.seed.charAt(0) === prefix && t.seedNum === seedNum;
    });
    if (cands.length < 2) return;
    var matched = matchPlayinWinner(wName, cands);
    if (matched) _playinResults[pk] = matched.name;
    return;
  }

  // Regular round game
  if (!regionMatch) {
    // Final Four or Championship
    if (note.indexOf('Final Four') !== -1 || note.indexOf('Semifinal') !== -1) {
      processF4Game(winner, loser, wScore, lScore);
    } else if (note.indexOf('Championship') !== -1 || note.indexOf('Final') !== -1) {
      processChampGame(winner, loser, wScore, lScore);
    }
    return;
  }

  var prefix = _espnRegionMap[regionMatch[1]];
  var roundMatch = note.match(/1st Round|2nd Round|Sweet 16|Elite Eight|Regional Final/);
  if (!prefix || !roundMatch || !wSeed || !lSeed) return;
  var round = _espnRoundMap[roundMatch[0]];
  if (round === undefined) return;

  var wPos = _seedPos[wSeed];
  var lPos = _seedPos[lSeed];
  if (wPos === undefined || lPos === undefined) return;

  var gameIdx = Math.floor(wPos / Math.pow(2, round + 1));
  var wTeamIdx = Math.floor(wPos / Math.pow(2, round)) % 2;
  var gid = prefix + '-' + round + '-' + gameIdx;

  var s = wTeamIdx === 0 ? [wScore, lScore] : [lScore, wScore];
  _completedGames[gid] = { w: wTeamIdx, s: s };
}

function processF4Game(winner, loser, wScore, lScore) {
  var wMapped = espnToOurName(winner.team.shortDisplayName);
  var lMapped = espnToOurName(loser.team.shortDisplayName);
  var wTeam = _originalTeams.find(function(t) { return t.name === wMapped; });
  var lTeam = _originalTeams.find(function(t) { return t.name === lMapped; });
  if (!wTeam || !lTeam) return;
  var wp = wTeam.seed.charAt(0), lp = lTeam.seed.charAt(0);
  var gid, teamIdx;
  if ((wp === 'W' || wp === 'X') && (lp === 'W' || lp === 'X')) {
    gid = 'f4-0'; teamIdx = wp === 'W' ? 0 : 1;
  } else if ((wp === 'Y' || wp === 'Z') && (lp === 'Y' || lp === 'Z')) {
    gid = 'f4-1'; teamIdx = wp === 'Y' ? 0 : 1;
  } else return;
  var s = teamIdx === 0 ? [wScore, lScore] : [lScore, wScore];
  _completedGames[gid] = { w: teamIdx, s: s };
}

function processChampGame(winner, loser, wScore, lScore) {
  var wMapped = espnToOurName(winner.team.shortDisplayName);
  var lMapped = espnToOurName(loser.team.shortDisplayName);
  var wTeam = _originalTeams.find(function(t) { return t.name === wMapped; });
  var lTeam = _originalTeams.find(function(t) { return t.name === lMapped; });
  if (!wTeam || !lTeam) return;
  var wp = wTeam.seed.charAt(0);
  // champ game: f4-0 winner (W/X) at idx 0, f4-1 winner (Y/Z) at idx 1
  var teamIdx = (wp === 'W' || wp === 'X') ? 0 : 1;
  var s = teamIdx === 0 ? [wScore, lScore] : [lScore, wScore];
  _completedGames['champ'] = { w: teamIdx, s: s };
}

function fetchTournamentResults() {
  // Fetch all tournament dates from First Four through today
  var season = _bracketSeason;
  var dates = [];
  var d = new Date(season, 2, 17); // March 17 of tournament year
  var today = new Date(); today.setHours(23, 59, 59);
  var endDate = new Date(season, 3, 10); // April 10 hard stop
  var stop = today < endDate ? today : endDate;
  while (d <= stop) {
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var dd = String(d.getDate()).padStart(2, '0');
    dates.push(y + m + dd);
    d.setDate(d.getDate() + 1);
  }

  if (dates.length === 0) {
    updateTourneyStatus();
    return;
  }

  var base = 'https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard';
  Promise.all(dates.map(function(dt) {
    return fetch(base + '?dates=' + dt + '&groups=100&limit=50')
      .then(function(r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .catch(function(err) {
        console.warn('ESPN API error for date ' + dt + ':', err.message);
        return { events: [] };
      });
  })).then(function(results) {
    _completedGames = {};
    _playinResults = {};
    results.forEach(function(data) {
      if (!data.events) return;
      data.events.forEach(processEspnGame);
    });
    rebuildFromResults();
    updateTourneyStatus();
  }).catch(function(err) {
    console.error('Failed to fetch tournament results:', err);
    updateTourneyStatus();
  });
}

function computeAccuracyComparison() {
  var completedKeys = Object.keys(_completedGames);
  if (!completedKeys.length) return null;

  var modelCorrect = 0, seedCorrect = 0, total = 0;
  var modelUpsetHits = 0, modelUpsetMisses = 0, seedUpsetMisses = 0;
  var roundPoints = [1, 2, 4, 8, 16, 32];
  var modelScore = 0, seedScore = 0;

  // Walk bracket to get team pairs for each completed game
  ['W', 'X', 'Y', 'Z'].forEach(function(prefix) {
    var teams = _seedOrder.map(function(s) {
      var cands = _originalTeams.filter(function(t) {
        return t.seed.charAt(0) === prefix && t.seedNum === s;
      });
      if (!cands.length) return null;
      if (cands.length > 1) {
        var pk = prefix + s;
        if (_playinResults[pk]) {
          var w = cands.find(function(t) { return t.name === _playinResults[pk]; });
          if (w) return w;
        }
      }
      return cands.reduce(function(a, b) { return a.r64 > b.r64 ? a : b; });
    });

    var slots = teams;
    for (var round = 0; round <= 3; round++) {
      var nextSlots = [];
      var pts = roundPoints[round] || 1;
      for (var i = 0; i < slots.length; i += 2) {
        var a = slots[i], b = slots[i + 1];
        var gid = prefix + '-' + round + '-' + Math.floor(i / 2);
        var completed = _completedGames[gid];
        var modelPred = _predictions[gid];

        if (completed && a && b) {
          total++;
          var actual = completed.w;
          // Seed pick: lower seedNum = higher seed = index 0 if a.seedNum < b.seedNum
          var seedPick = (a.seedNum <= b.seedNum) ? 0 : 1;
          var isUpset = (actual !== seedPick);

          if (modelPred === actual) {
            modelCorrect++;
            modelScore += pts;
            if (isUpset) modelUpsetHits++;
          } else {
            if (modelPred !== seedPick) modelUpsetMisses++;
          }
          if (seedPick === actual) {
            seedCorrect++;
            seedScore += pts;
          } else {
            seedUpsetMisses++;
          }

          nextSlots.push(completed.w === 0 ? a : b);
        } else {
          // Use model prediction or first available for advancing
          var rk = ['r64', 'r32', 's16', 'e8'][round];
          var pred = (a && b) ? (a[rk] >= b[rk] ? a : b) : (a || b);
          nextSlots.push(pred);
        }
      }
      slots = nextSlots;
    }
  });

  // Final Four & Championship
  var f4Games = [['f4-0'], ['f4-1'], ['champ']];
  // These are harder to map without full team context; skip for now if not completed
  // (the region games are the bulk of the comparison)

  if (total === 0) return null;
  return {
    total: total,
    modelCorrect: modelCorrect,
    seedCorrect: seedCorrect,
    modelPct: (modelCorrect / total * 100).toFixed(1),
    seedPct: (seedCorrect / total * 100).toFixed(1),
    modelScore: modelScore,
    seedScore: seedScore,
    modelUpsetHits: modelUpsetHits,
    modelUpsetMisses: modelUpsetMisses,
    seedUpsetMisses: seedUpsetMisses
  };
}

function updateTourneyStatus() {
  var el = document.getElementById('tourney-status');
  if (!el) return;
  var season = _bracketSeason;
  var now = new Date();
  var start = new Date(season, 2, 17); // March 17
  var end = new Date(season, 3, 7);    // Day after April 6 championship
  if (now < start) {
    el.textContent = '';
  } else if (now < end && !_completedGames['champ']) {
    var html = 'March Madness ' + season + ' is <span style="color: var(--green); font-weight: 600;">going on right now</span>' +
      '<br>This is <em style="color: var(--accent); font-style: italic;">my bracket</em>';

    var acc = computeAccuracyComparison();
    if (acc && acc.total > 0) {
      html += '<div class="accuracy-comparison">' +
        '<div class="acc-cards">' +
          '<div class="acc-card">' +
            '<div class="acc-card-label">My Model</div>' +
            '<div class="acc-card-value">' + acc.modelPct + '%</div>' +
            '<div class="acc-card-pct">' + acc.modelCorrect + '/' + acc.total + '</div>' +
          '</div>' +
          '<div class="acc-vs">vs</div>' +
          '<div class="acc-card">' +
            '<div class="acc-card-label">Higher Seed</div>' +
            '<div class="acc-card-value">' + acc.seedPct + '%</div>' +
            '<div class="acc-card-pct">' + acc.seedCorrect + '/' + acc.total + '</div>' +
          '</div>' +
        '</div>' +
      '</div>';
    }
    el.innerHTML = html;
  } else {
    el.textContent = 'March Madness ' + season + ' is over';
  }
  el.style.opacity = '1';
}
