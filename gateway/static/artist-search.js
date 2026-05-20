class ArtistSearch {
    constructor(containerId, options = {}) {
        this.container = document.getElementById(containerId);
        this.options = {
            minArtists: options.minArtists || 0,
            maxArtists: options.maxArtists || 10,
            onSelectionChange: options.onSelectionChange || (() => { }),
            onContinue: options.onContinue || null,
            ...options
        };

        this.selectedArtists = [];
        this.selectedAlbums = [];
        this.searchResults = [];
        this.albumResults = [];
        this.searchTimeout = null;
        this.recommendationsCache = {};
        this.loadingArtists = new Set();
        this.pendingPromises = new Map();

        this.render();
        this.attachEventListeners();
    }

    render() {
        this.container.innerHTML = `
            <div class="search-modal">
                <header class="search-modal__head">
                    <div class="search-modal__head-l">
                        <span class="search-modal__kicker">Búsqueda · resultados mezclados</span>
                        <h2 class="search-modal__title">Encuentra <em>tu pila</em>.</h2>
                    </div>
                    <button class="search-modal__x" id="search-modal-close-btn" aria-label="Cerrar">✕</button>
                </header>

                <div class="search-bar">
                    <span class="search-bar__icon" aria-hidden="true">⌕</span>
                    <input
                        type="text"
                        id="artist-search-input"
                        class="search-bar__input"
                        placeholder="Radiohead, post-punk, Kind of Blue…"
                        aria-label="Buscar artistas o álbumes"
                        autocomplete="off"
                    />
                    <span id="search-bar-count" class="search-bar__count"></span>
                    <button class="search-bar__clear" id="clear-search-btn" aria-label="Limpiar búsqueda">✕</button>
                </div>

                <div class="search-legend" aria-hidden="true">
                    <span class="search-legend__item">
                        <span class="search-legend__swatch search-legend__swatch--circle"></span>
                        <span><b>Artista</b> · recomendaremos sus vinilos</span>
                    </span>
                    <span class="search-legend__sep">/</span>
                    <span class="search-legend__item">
                        <span class="search-legend__swatch search-legend__swatch--square"></span>
                        <span><b>Álbum</b> · entra directo a tu lista</span>
                    </span>
                    <span class="search-legend__hint">redondo o cuadrado.</span>
                </div>

                <div class="search-body">
                    <div class="search-grid" id="search-results-grid"></div>
                </div>

                <div class="search-dock" id="search-dock" style="display:none"></div>

                <footer class="search-foot">
                    <div class="search-foot__info">
                        <span><b class="accent" id="count-directos">0</b>&nbsp;álbumes directos</span>
                        <span><b class="accent" id="count-algoritmo">0</b>&nbsp;artistas → algoritmo</span>
                    </div>
                    ${this.options.onContinue ? `
                        <button class="search-cta" id="search-cta-btn" disabled>
                            Ver recomendaciones →
                        </button>
                    ` : ''}
                </footer>
            </div>
        `;
    }

    attachEventListeners() {
        const searchInput = document.getElementById('artist-search-input');
        const clearBtn = document.getElementById('clear-search-btn');
        const ctaBtn = document.getElementById('search-cta-btn');
        const closeBtn = document.getElementById('search-modal-close-btn');

        searchInput.addEventListener('input', (e) => {
            const query = e.target.value.trim();
            clearBtn.style.display = query.length > 0 ? 'block' : 'none';
            if (this.searchTimeout) clearTimeout(this.searchTimeout);
            if (query.length >= 2) {
                this.searchTimeout = setTimeout(() => this.performSearch(query), 300);
            } else {
                this.clearSearchResults();
            }
        });

        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                searchInput.value = '';
                clearBtn.style.display = 'none';
                this.clearSearchResults();
                searchInput.focus();
            });
        }

        if (ctaBtn) {
            ctaBtn.addEventListener('click', async () => {
                if (this.options.onContinue && this.isValidSelection()) {
                    await this.options.onContinue(this.selectedArtists, this);
                }
            });
        }

        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                if (typeof closeArtistSearch === 'function') closeArtistSearch();
            });
        }
    }

    async performSearch(query) {
        const grid = document.getElementById('search-results-grid');
        // Skeleton tiles
        grid.innerHTML = Array(12).fill(`<div class="search-skel"></div>`).join('');
        const countEl = document.getElementById('search-bar-count');
        if (countEl) countEl.textContent = '';

        try {
            const data = await apiCall(`/api/search?q=${encodeURIComponent(query)}`);
            this.searchResults = data.artists || [];
            this.albumResults = data.albums || [];
            this.renderSearchResults();
        } catch (error) {
            console.error('Search failed:', error);
            grid.innerHTML = '<div class="search-empty"><p>Error al buscar. Inténtalo de nuevo.</p></div>';
        }
    }

    renderSearchResults() {
        const grid = document.getElementById('search-results-grid');
        const countEl = document.getElementById('search-bar-count');

        if (!grid) return;

        const hasArtists = this.searchResults.length > 0;
        const hasAlbums = this.albumResults && this.albumResults.length > 0;

        if (!hasArtists && !hasAlbums) {
            const q = document.getElementById('artist-search-input')?.value || '';
            grid.innerHTML = `<div class="search-empty"><span class="search-modal__kicker">Sin coincidencias</span><p>No encontramos <em>"${q}"</em>.</p></div>`;
            if (countEl) countEl.textContent = '';
            return;
        }

        const hasGoodArtist = this.searchResults.some(a => a.relevance === 'high' || a.relevance === 'exact');
        const highArtists = this.searchResults.filter(a => a.relevance === 'high' || a.relevance === 'exact');
        const lowArtists  = this.searchResults.filter(a => a.relevance === 'low');
        const hasExact = this.searchResults.some(a => a.relevance === 'exact');

        // Build unified ordered list: [{kind:'artist'|'album', data}]
        let items = [];
        if (hasGoodArtist) {
            items = [
                ...highArtists.map(a => ({ kind: 'artist', data: a })),
                ...(hasAlbums ? this.albumResults.map(a => ({ kind: 'album', data: a })) : []),
                ...(!hasExact ? lowArtists.map(a => ({ kind: 'artist', data: a })) : []),
            ];
        } else {
            items = [
                ...(hasAlbums ? this.albumResults.map(a => ({ kind: 'album', data: a })) : []),
                ...this.searchResults.map(a => ({ kind: 'artist', data: a })),
            ];
        }

        // Strip items without a real photo (safety net — backend also filters)
        items = items.filter(item =>
            item.kind === 'artist' ? !!item.data.image_url : !!item.data.cover_url
        );

        // Max 24 items
        items = items.slice(0, 24);

        if (countEl) countEl.textContent = `${items.length} de ${this.searchResults.length + (this.albumResults?.length || 0)}`;

        grid.innerHTML = items.map(item => this._renderTile(item)).join('');
        this.attachTileListeners();
    }

    _renderTile(item) {
        if (item.kind === 'artist') {
            const a = item.data;
            const isSelected = this.selectedArtists.some(s => s.name === a.name);
            const isDisabled = !isSelected && this.selectedArtists.length >= this.options.maxArtists;
            const artistJson = JSON.stringify(a).replace(/'/g, '&apos;').replace(/"/g, '&quot;');
            const imgHtml = a.image_url
                ? `<img src="${a.image_url}" alt="${a.name}" loading="lazy">`
                : `<div class="search-tile__art-placeholder">🎵</div>`;
            const genre = a.genres && a.genres.length > 0 ? a.genres.slice(0, 2).join(', ') : 'Artista';
            return `
                <button type="button"
                    class="search-tile search-tile--artist ${isSelected ? 'search-tile--on' : ''} ${isDisabled ? 'search-tile--disabled' : ''}"
                    data-kind="artist"
                    data-artist="${artistJson}"
                    aria-pressed="${isSelected}"
                    aria-label="Artista ${a.name}"
                    ${isDisabled ? 'disabled' : ''}>
                    <div class="search-tile__band search-tile__band--art">
                        <span>Artista</span>
                        <span class="search-tile__band-action">recomendación</span>
                    </div>
                    <div class="search-tile__body">
                        <div class="search-tile__art search-tile__art--circle">${imgHtml}</div>
                        <span class="search-tile__name">${a.name}</span>
                        <span class="search-tile__sub">${genre}</span>
                    </div>
                    <span class="search-tile__add" aria-hidden="true">${isSelected ? '✓' : '+'}</span>
                </button>
            `;
        } else {
            // album
            const al = item.data;
            const isSelected = this.selectedAlbums.some(s => s.title === al.title && s.artist_name === al.artist_name);
            const albumJson = JSON.stringify(al).replace(/'/g, '&apos;').replace(/"/g, '&quot;');
            const imgHtml = al.cover_url
                ? `<img src="${al.cover_url}" alt="${al.title}" loading="lazy">`
                : `<div class="search-tile__art-placeholder">💿</div>`;
            const sub = [al.artist_name, al.year].filter(Boolean).join(' · ');
            return `
                <button type="button"
                    class="search-tile search-tile--album ${isSelected ? 'search-tile--on' : ''}"
                    data-kind="album"
                    data-album="${albumJson}"
                    aria-pressed="${isSelected}"
                    aria-label="Álbum ${al.title} de ${al.artist_name}">
                    <div class="search-tile__band search-tile__band--lp">
                        <span>Álbum</span>
                        <span class="search-tile__band-action">directo</span>
                    </div>
                    <div class="search-tile__body">
                        <div class="search-tile__art">${imgHtml}</div>
                        <span class="search-tile__name"><em>${al.title}</em></span>
                        <span class="search-tile__sub">${sub}</span>
                    </div>
                    <span class="search-tile__add" aria-hidden="true">${isSelected ? '✓' : '+'}</span>
                </button>
            `;
        }
    }

    attachTileListeners() {
        document.querySelectorAll('.search-tile--artist').forEach(tile => {
            tile.addEventListener('click', () => {
                if (tile.disabled) return;
                const artist = JSON.parse(tile.dataset.artist.replace(/&quot;/g, '"').replace(/&apos;/g, "'"));
                const isSelected = this.selectedArtists.some(a => a.name === artist.name);
                if (isSelected) this.removeArtist(artist.name);
                else if (this.selectedArtists.length < this.options.maxArtists) this.addArtist(artist);
            });
        });

        document.querySelectorAll('.search-tile--album').forEach(tile => {
            tile.addEventListener('click', async () => {
                const al = JSON.parse(tile.dataset.album.replace(/&quot;/g, '"').replace(/&apos;/g, "'"));
                const isSelected = this.selectedAlbums.some(s => s.title === al.title && s.artist_name === al.artist_name);
                if (isSelected) {
                    // deselect: find index and remove
                    const idx = this.selectedAlbums.findIndex(s => s.title === al.title && s.artist_name === al.artist_name);
                    if (idx >= 0) this.removeAlbum(idx);
                } else {
                    // optimistic select
                    tile.classList.add('search-tile--on');
                    const addBtn = tile.querySelector('.search-tile__add');
                    if (addBtn) addBtn.textContent = '✓';
                    await this.addAlbum(al, tile);
                }
            });
        });
    }

    renderDock() {
        const dock = document.getElementById('search-dock');
        if (!dock) return;

        const total = this.selectedArtists.length + this.selectedAlbums.length;
        if (total === 0) { dock.style.display = 'none'; return; }
        dock.style.display = 'flex';

        const pillsHtml = [
            ...this.selectedArtists.map((a, i) => {
                const thumb = a.image_url
                    ? `<img src="${a.image_url}" alt="${a.name}">`
                    : `<span style="font-size:11px">🎵</span>`;
                const isLoading = this.loadingArtists.has(a.name);
                return `
                    <span class="search-pill">
                        <span class="search-pill__thumb">${thumb}</span>
                        <span class="search-pill__type">ART</span>
                        <span class="search-pill__name">${a.name}${isLoading ? ' ⏳' : ''}</span>
                        <button class="search-pill__rm" data-kind="artist" data-name="${a.name}" aria-label="Quitar ${a.name}">×</button>
                    </span>
                `;
            }),
            ...this.selectedAlbums.map((al, i) => {
                const thumb = al.cover_url
                    ? `<img src="${al.cover_url}" alt="${al.title}">`
                    : `<span style="font-size:11px">💿</span>`;
                return `
                    <span class="search-pill">
                        <span class="search-pill__thumb search-pill__thumb--sq">${thumb}</span>
                        <span class="search-pill__type">LP</span>
                        <span class="search-pill__name">${al.title}</span>
                        <button class="search-pill__rm" data-kind="album" data-index="${i}" aria-label="Quitar ${al.title}">×</button>
                    </span>
                `;
            })
        ].join('');

        dock.innerHTML = `
            <span class="search-dock__label">Tu lista · ${total}</span>
            <div class="search-dock__list">${pillsHtml}</div>
        `;

        dock.querySelectorAll('.search-pill__rm').forEach(btn => {
            btn.addEventListener('click', () => {
                if (btn.dataset.kind === 'artist') this.removeArtist(btn.dataset.name);
                else this.removeAlbum(parseInt(btn.dataset.index));
            });
        });
    }

    updateUI() {
        this.renderSearchResults();
        this.renderDock();
        this.updateCTA();
        this.options.onSelectionChange(this.selectedArtists);
    }

    updateCTA() {
        const ctaBtn = document.getElementById('search-cta-btn');
        const countDirectos = document.getElementById('count-directos');
        const countAlgoritmo = document.getElementById('count-algoritmo');

        if (countDirectos) countDirectos.textContent = this.selectedAlbums.length;
        if (countAlgoritmo) countAlgoritmo.textContent = this.selectedArtists.length;

        if (ctaBtn) {
            const isValid = this.isValidSelection();
            const isLoading = this.loadingArtists.size > 0;
            ctaBtn.disabled = !isValid || isLoading;
            ctaBtn.textContent = isLoading
                ? `Cargando ${this.loadingArtists.size}…`
                : 'Ver recomendaciones →';
        }
    }

    // Keep alias for any external callers
    updateContinueButton() {
        this.updateCTA();
    }

    clearSearchResults() {
        const grid = document.getElementById('search-results-grid');
        if (grid) grid.innerHTML = '';
        this.searchResults = [];
        this.albumResults = [];
        const countEl = document.getElementById('search-bar-count');
        if (countEl) countEl.textContent = '';
    }

    isValidSelection() {
        return this.selectedArtists.length >= this.options.minArtists || this.selectedAlbums.length > 0;
    }

    async addAlbum(album, button) {
        // Get or create user ID
        let userId = localStorage.getItem('userId');

        // If no userId, this is a guest - we need to create a user first
        if (!userId || userId === 'null' || userId === 'undefined') {
            try {
                // Create a guest user
                const createUserResp = await fetch('/auth/guest', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });

                if (createUserResp.ok) {
                    const userData = await createUserResp.json();
                    userId = userData.user_id;
                    localStorage.setItem('userId', userId);
                    console.log('Created guest user:', userId);
                } else {
                    alert('Error al crear usuario. Por favor, recarga la página.');
                    // Revert optimistic UI
                    if (button) {
                        button.classList.remove('search-tile--on');
                        const addBtn = button.querySelector('.search-tile__add');
                        if (addBtn) addBtn.textContent = '+';
                    }
                    return;
                }
            } catch (error) {
                console.error('Error creating guest user:', error);
                alert('Error al crear usuario. Por favor, intenta de nuevo.');
                // Revert optimistic UI
                if (button) {
                    button.classList.remove('search-tile--on');
                    const addBtn = button.querySelector('.search-tile__add');
                    if (addBtn) addBtn.textContent = '+';
                }
                return;
            }
        }

        // Disable button during request
        if (button) button.disabled = true;

        try {
            const response = await fetch(`/api/users/${userId}/albums`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    title: album.title,
                    artist_name: album.artist_name,
                    cover_url: album.cover_url,
                    discogs_id: album.discogs_id
                })
            });

            if (response.ok) {
                const data = await response.json();
                console.log('Album added:', data);

                // Add to selected albums list
                this.selectedAlbums.push({
                    title: album.title,
                    artist_name: album.artist_name,
                    cover_url: album.cover_url
                });

                this.renderDock();
                this.updateCTA();
            } else {
                const error = await response.json();
                console.error('Failed to add album:', error);
                alert(`Error al añadir álbum: ${error.detail || 'Error desconocido'}`);
                // Revert optimistic UI
                if (button) {
                    button.classList.remove('search-tile--on');
                    button.disabled = false;
                    const addBtn = button.querySelector('.search-tile__add');
                    if (addBtn) addBtn.textContent = '+';
                }
            }
        } catch (error) {
            console.error('Error adding album:', error);
            alert('Error al añadir álbum. Por favor, intenta de nuevo.');
            // Revert optimistic UI
            if (button) {
                button.classList.remove('search-tile--on');
                button.disabled = false;
                const addBtn = button.querySelector('.search-tile__add');
                if (addBtn) addBtn.textContent = '+';
            }
        }
    }

    async addArtist(artist) {
        if (this.selectedArtists.length >= this.options.maxArtists) {
            return;
        }

        if (!this.selectedArtists.some(a => a.name === artist.name)) {
            this.selectedArtists.push(artist);
            this.loadingArtists.add(artist.name);
            this.updateUI();

            // Get userId to enable persistent recommendations (Upgrade/Complete)
            const userId = localStorage.getItem('userId');

            const fetchPromise = (async () => {
                try {
                    const response = await fetch('/api/recommendations/artist-single', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            artist_name: artist.name,
                            top_albums: 3,
                            user_id: userId ? parseInt(userId) : null,
                            preview: true,
                        })
                    });

                    if (response.ok) {
                        const data = await response.json();
                        const recs = data.recommendations || [];
                        if (recs.length > 0) {
                            this.recommendationsCache[artist.name] = {
                                status: 'success',
                                recommendations: recs,
                                timestamp: Date.now()
                            };
                            console.log(`✓ Cached ${recs.length} recommendations for ${artist.name}`);
                        } else {
                            // Backend found nothing even after all fallbacks (Discogs + Spotify)
                            console.warn(`⚠ No albums found for ${artist.name} after all fallbacks`);
                            this.recommendationsCache[artist.name] = {
                                status: 'error',
                                error: 'No se encontraron álbumes',
                                timestamp: Date.now()
                            };
                        }
                    } else {
                        console.warn(`⚠ Pre-fetch failed for ${artist.name} (${response.status})`);
                        this.recommendationsCache[artist.name] = {
                            status: 'error',
                            error: `Error ${response.status}`,
                            timestamp: Date.now()
                        };
                    }
                } catch (error) {
                    console.error(`✗ Pre-fetch network error for ${artist.name}:`, error);
                    this.recommendationsCache[artist.name] = {
                        status: 'error',
                        error: error.message,
                        timestamp: Date.now()
                    };
                } finally {
                    this.loadingArtists.delete(artist.name);
                    this.pendingPromises.delete(artist.name);
                    this.updateUI();
                }
            })();

            this.pendingPromises.set(artist.name, fetchPromise);
        }
    }

    async fetchSpotifyRecommendations(artist) {
        try {
            const response = await fetch('/api/recommendations/spotify', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ artist_name: artist.name, top_albums: 5 })
            });

            if (response.ok) {
                const data = await response.json();
                const recs = data.recommendations || [];
                if (recs.length > 0) {
                    this.recommendationsCache[artist.name] = {
                        status: 'success',
                        recommendations: recs,
                        timestamp: Date.now()
                    };
                    console.log(`✓ Cached ${recs.length} recommendations for ${artist.name} (Spotify Fallback)`);
                } else {
                    this.recommendationsCache[artist.name] = {
                        status: 'error',
                        error: 'No albums found on Spotify',
                        timestamp: Date.now()
                    };
                }
            } else {
                const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
                this.recommendationsCache[artist.name] = {
                    status: 'error',
                    error: errorData.detail || `HTTP ${response.status}`,
                    timestamp: Date.now()
                };
            }
        } catch (error) {
            this.recommendationsCache[artist.name] = {
                status: 'error',
                error: error.message || 'Network error',
                timestamp: Date.now()
            };
        }
    }

    removeArtist(artistName) {
        this.selectedArtists = this.selectedArtists.filter(a => a.name !== artistName);
        delete this.recommendationsCache[artistName];
        this.loadingArtists.delete(artistName);
        this.pendingPromises.delete(artistName);
        console.log(`✗ Removed ${artistName} and its cached recommendations`);
        this.updateUI();
    }

    removeAlbum(index) {
        this.selectedAlbums.splice(index, 1);
        this.renderDock();
        this.updateCTA();
        this.renderSearchResults(); // re-render to deselect tile
    }

    async waitForAllPendingRecommendations() {
        if (this.pendingPromises.size === 0) {
            return;
        }

        console.log(`⏳ Waiting for ${this.pendingPromises.size} pending recommendations to complete...`);
        const allPromises = Array.from(this.pendingPromises.values());
        await Promise.allSettled(allPromises);
        console.log('✓ All pending recommendations completed');
    }

    getCachedRecommendations() {
        const allRecommendations = [];
        for (const artistName of this.selectedArtists.map(a => a.name)) {
            const cached = this.recommendationsCache[artistName];
            if (cached && cached.status === 'success' && cached.recommendations) {
                allRecommendations.push(...cached.recommendations);
            }
        }
        return allRecommendations;
    }

    isLoadingComplete() {
        if (this.loadingArtists.size > 0) {
            return false;
        }
        return this.selectedArtists.every(artist => {
            const cached = this.recommendationsCache[artist.name];
            return cached !== undefined;
        });
    }

    hasAllSuccessful() {
        if (this.selectedArtists.length === 0) {
            return false;
        }
        return this.selectedArtists.every(artist => {
            const cached = this.recommendationsCache[artist.name];
            return cached && cached.status === 'success';
        });
    }

    getLoadingStatus() {
        const successCount = this.selectedArtists.filter(artist => {
            const cached = this.recommendationsCache[artist.name];
            return cached && cached.status === 'success';
        }).length;

        const errorCount = this.selectedArtists.filter(artist => {
            const cached = this.recommendationsCache[artist.name];
            return cached && cached.status === 'error';
        }).length;

        return {
            total: this.selectedArtists.length,
            success: successCount,
            error: errorCount,
            loading: this.loadingArtists.size,
            isComplete: this.isLoadingComplete(),
            hasAllSuccessful: this.hasAllSuccessful()
        };
    }

    getSelectedArtists() {
        return this.selectedArtists;
    }

    setSelectedArtists(artists) {
        this.selectedArtists = artists;
        this.updateUI();
    }

    async restoreArtists(artistNames) {
        console.log(`🔄 Restoring ${artistNames.length} artists:`, artistNames);

        const fetchAndAddArtist = async (name) => {
            try {
                const response = await fetch(`/api/spotify/search/artists?q=${encodeURIComponent(name)}`);
                if (response.ok) {
                    const data = await response.json();
                    if (data.artists && data.artists.length > 0) {
                        const artist = data.artists[0];
                        console.log(`✓ Restored artist: ${artist.name}`);
                        await this.addArtist(artist);
                        return { success: true, name };
                    } else {
                        console.warn(`⚠ Could not find artist ${name} in Spotify`);
                        return { success: false, name, reason: 'Not found' };
                    }
                } else {
                    console.error(`✗ Failed to search for ${name} (HTTP ${response.status})`);
                    return { success: false, name, reason: `HTTP ${response.status}` };
                }
            } catch (error) {
                console.error(`✗ Error restoring artist ${name}:`, error);
                return { success: false, name, reason: error.message };
            }
        };

        const results = await Promise.all(artistNames.map(fetchAndAddArtist));
        const successful = results.filter(r => r.success).length;
        const failed = results.filter(r => !r.success);

        console.log(`✓ Restored ${successful}/${artistNames.length} artists successfully`);
        if (failed.length > 0) {
            console.warn(`⚠ Failed to restore ${failed.length} artists:`, failed);
        }
    }
}
