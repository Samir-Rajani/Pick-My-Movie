const searchInput = document.querySelector('#movie-search');
const searchResults = document.querySelector('#search-results');
const selected = document.querySelector('#selected');
const pickCount = document.querySelector('#pick-count');
const recs = document.querySelector('#recommendations');
const status = document.querySelector('#results-status');
const genreFilter = document.querySelector('#genre-filter');
const liked = new Map();
let searchToken = 0;
let recommendationToken = 0;
let timer;
const pickMyMovieBase = location.pathname === '/pickmymovie' || location.pathname.startsWith('/pickmymovie/') ? '/pickmymovie' : '';
document.querySelector('.brand').setAttribute('href', `${pickMyMovieBase}/`);

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response.json();
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function save() {
  localStorage.setItem('pickmymovie-liked', JSON.stringify([...liked.values()]));
}

function renderPicked() {
  selected.replaceChildren();
  pickCount.textContent = `${liked.size} SELECTED`;
  if (!liked.size) selected.append(element('div', 'empty-picked', 'Your favorites will appear here. Start searching to add a movie.'));
  for (const movie of liked.values()) {
    const chip = element('button', 'chip');
    chip.type = 'button'; chip.title = `Remove ${movie.title}`; chip.setAttribute('aria-label', `Remove ${movie.title}`);
    chip.append(element('span', '', movie.title), element('b', '', '×'));
    chip.addEventListener('click', () => { liked.delete(movie.id); save(); renderPicked(); recommend(); search(); });
    selected.append(chip);
  }
}

async function search() {
  const query = searchInput.value.trim();
  const token = ++searchToken;
  try {
    const movies = await getJson(`${pickMyMovieBase}/api/movies?q=${encodeURIComponent(query)}`);
    if (token !== searchToken) return;
    searchResults.replaceChildren();
    const available = movies.filter(movie => !liked.has(movie.id));
    if (!available.length) { searchResults.append(element('div', 'search-help', query ? 'No more matching films. Try another title.' : 'No films available.')); return; }
    for (const movie of available) {
      const button = element('button', 'search-item'); button.type = 'button';
      const info = element('div'); info.append(element('strong', '', movie.title), element('small', '', movie.genres.slice(0, 3).join(' · ') || 'Unclassified'));
      button.append(info, element('span', 'add', '+'));
      button.addEventListener('click', () => { liked.set(movie.id, movie); save(); renderPicked(); recommend(); search(); });
      searchResults.append(button);
    }
  } catch { searchResults.replaceChildren(element('div', 'search-help', 'Search is unavailable. Check that the local server is running.')); }
}

async function recommend() {
  const token = ++recommendationToken;
  if (!liked.size) { recs.replaceChildren(); status.textContent = 'Choose a film above to see recommendations.'; return; }
  status.textContent = 'Finding your matches…';
  try {
    const params = new URLSearchParams({liked: [...liked.keys()].join(','), genre: genreFilter.value, limit: '12'});
    const movies = await getJson(`${pickMyMovieBase}/api/recommendations?${params}`);
    if (token !== recommendationToken) return;
    recs.replaceChildren();
    status.textContent = `${movies.length} ${movies.length === 1 ? 'FILM' : 'FILMS'} SELECTED FOR YOUR TASTE`;
    if (!movies.length) { recs.append(element('div', 'placeholder', 'No matches for this genre. Try another filter.')); return; }
    movies.forEach((movie, index) => {
      const card = element('article', 'movie-card');
      const top = element('div', 'card-top'); top.append(element('span', 'card-num', String(index + 1).padStart(2, '0') + ' / MATCH'), element('span', 'card-score', `SIMILARITY ${Math.round(movie.score * 100)}`));
      card.append(top, element('h3', '', movie.title), element('div', 'movie-meta', movie.genres.slice(0, 3).join('  ·  ')), element('div', 'movie-reason', `✦ ${movie.reason}`));
      const add = element('button', 'card-like', '+'); add.type = 'button'; add.title = `Add ${movie.title} to favorites`; add.setAttribute('aria-label', add.title);
      add.addEventListener('click', () => { liked.set(movie.id, movie); save(); renderPicked(); recommend(); search(); document.querySelector('#taste').scrollIntoView({behavior:'smooth'}); });
      card.append(add); recs.append(card);
    });
  } catch { status.textContent = 'Recommendations are unavailable. Check that the local server is running.'; }
}

searchInput.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(search, 150); });
genreFilter.addEventListener('change', recommend);
document.querySelector('#clear-button').addEventListener('click', () => { liked.clear(); save(); renderPicked(); recommend(); search(); });

async function initialize() {
  try {
    const [health, genres] = await Promise.all([getJson(`${pickMyMovieBase}/api/health`), getJson(`${pickMyMovieBase}/api/genres`)]);
    document.querySelector('#data-mode').textContent = `${health.movies.toLocaleString()} FILMS · ${health.mode.toUpperCase()} MODE`;
    genres.forEach(genre => { const option = element('option', '', genre); option.value = genre; genreFilter.append(option); });
    for (const movie of JSON.parse(localStorage.getItem('pickmymovie-liked') || localStorage.getItem('cinemamatch-liked') || '[]')) if (movie && Number.isInteger(movie.id)) liked.set(movie.id, movie);
    renderPicked(); await search(); await recommend();
  } catch { searchResults.append(element('div', 'search-help', 'Could not connect to the movie catalog.')); }
}
initialize();
