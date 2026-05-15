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
        this.currentSearchFilter = 'all'; // 'all', 'artists', 'albums'
        this.showAllArtists = false; // Mobile: show all artists or just 2
        this.showAllAlbums = false; // Mobile: show all albums or just 2

        this.render();
        this.attachEventListeners();
    }

    renderSelectedAlbums() {
        const pillsContainer = document.getElementById('selected-albums-pills');
        const counter = document.getElementById('album-counter');

        if (!pillsContainer || !counter) return;

        counter.textContent = `${this.selectedAlbums.length} añadidos`;

        if (this.selectedAlbums.length === 0) {
            pillsContainer.innerHTML = '<div class="no-selection">Aún no has añadido álbumes</div>';
            return;
        }

        pillsContainer.innerHTML = this.selectedAlbums.map((album, index) => {
            return `
                <div class="album-pill">
                    ${album.cover_url
                    ? `<img src="${album.cover_url}" alt="${album.title}" class="pill-image" />`
                    : '<div class="pill-placeholder">💿</div>'
                }
                    <div class="pill-album-info">
                        <span class="pill-album-title">${album.title}</span>
                        <span class="pill-album-artist">${album.artist_name}</span>
                    </div>
                    <button class="pill-remove-btn" data-album-index="${index}">✕</button>
                </div>
            `;
        }).join('');

        this.attachAlbumPillRemoveListeners();
    }

    attachAlbumPillRemoveListeners() {
        const removeButtons = document.querySelectorAll('.album-pill .pill-remove-btn');
        removeButtons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                const index = parseInt(btn.dataset.albumIndex);
                this.removeAlbum(index);
            });
        });
    }

    removeAlbum(index) {
        this.selectedAlbums.splice(index, 1);
        this.renderSelectedAlbums();
        this.updateContinueButton();
        // Re-render search results to update button states
        this.renderSearchResults();
    }

    render() {
        this.container.innerHTML = `
            <div class="artist-search-modal">
                <div class="artist-search-header">
                    <h2>Selecciona hasta ${this.options.maxArtists} artistas o añade álbumes directamente.</h2>
                </div>
                
                <div class="artist-search-input-wrapper">
                    <input 
                        type="text" 
                        id="artist-search-input" 
                        placeholder="Busca música o busca vinilos..." 
                        class="artist-search-input"
                        autocomplete="off"
                    />
                    <button id="clear-search-btn" class="clear-search-btn" style="display: none;">✕</button>
                </div>
                
                <div id="search-results-container" class="search-results-container">
                    <div class="search-filter-tabs" id="search-filter-tabs" style="display: none;">
                        <button class="search-tab active" data-filter="all">Todos</button>
                        <button class="search-tab" data-filter="artists">Artistas</button>
                        <button class="search-tab" data-filter="albums">Álbumes</button>
                    </div>
                    <div id="search-results-grid" class="artist-grid"></div>
                </div>
                
                <div class="selected-artists-section">
                    <div class="selected-artists-header collapsible-header" id="artists-header">
                        <div class="header-content">
                            <span>Artistas seleccionados (opcional, máx. ${this.options.maxArtists})</span>
                            <span id="artist-counter" class="artist-counter">0/${this.options.maxArtists} seleccionados</span>
                        </div>
                        <span class="collapse-icon">▼</span>
                    </div>
                    <div id="selected-artists-pills" class="selected-artists-pills collapsible-content"></div>
                </div>

                <div class="selected-albums-section">
                    <div class="selected-albums-header collapsible-header" id="albums-header">
                        <div class="header-content">
                            <span>Álbumes añadidos</span>
                            <span id="album-counter" class="album-counter">0 añadidos</span>
                        </div>
                        <span class="collapse-icon">▼</span>
                    </div>
                    <div id="selected-albums-pills" class="selected-albums-pills collapsible-content"></div>
                </div>
                
                ${this.options.onContinue ? `
                    <button id="continue-btn" class="continue-btn" disabled>
                        Continuar
                    </button>
                ` : ''}
            </div>
        `;
    }

    attachEventListeners() {
        const searchInput = document.getElementById('artist-search-input');
        const clearBtn = document.getElementById('clear-search-btn');
        const continueBtn = document.getElementById('continue-btn');

        searchInput.addEventListener('input', (e) => {
            const query = e.target.value.trim();

            if (query.length > 0) {
                clearBtn.style.display = 'block';
            } else {
                clearBtn.style.display = 'none';
            }

            if (this.searchTimeout) {
                clearTimeout(this.searchTimeout);
            }

            if (query.length >= 2) {
                this.searchTimeout = setTimeout(() => {
                    this.performSearch(query);
                }, 300);
            } else {
                this.clearSearchResults();
            }
        });

        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                searchInput.value = '';
                clearBtn.style.display = 'none';
                this.clearSearchResults();
            });
        }

        if (continueBtn) {
            continueBtn.addEventListener('click', async () => {
                if (this.options.onContinue && this.isValidSelection()) {
                    await this.options.onContinue(this.selectedArtists, this);
                }
            });
        }

        // Attach filter tab listeners
        this.attachFilterTabListeners();

        // Attach collapsible listeners
        this.attachCollapsibleListeners();
    }

    attachCollapsibleListeners() {
        const artistsHeader = document.getElementById('artists-header');
        const albumsHeader = document.getElementById('albums-header');

        // Initialize as collapsed on mobile
        if (window.innerWidth <= 768) {
            const artistsContent = document.getElementById('selected-artists-pills');
            const albumsContent = document.getElementById('selected-albums-pills');

            if (artistsContent) artistsContent.classList.add('collapsed');
            if (albumsContent) albumsContent.classList.add('collapsed');

            const artistIcon = artistsHeader?.querySelector('.collapse-icon');
            const albumIcon = albumsHeader?.querySelector('.collapse-icon');

            if (artistIcon) artistIcon.classList.add('collapsed');
            if (albumIcon) albumIcon.classList.add('collapsed');
        }

        if (artistsHeader) {
            artistsHeader.addEventListener('click', () => {
                const content = document.getElementById('selected-artists-pills');
                const icon = artistsHeader.querySelector('.collapse-icon');

                content.classList.toggle('collapsed');
                icon.classList.toggle('collapsed');
            });
        }

        if (albumsHeader) {
            albumsHeader.addEventListener('click', () => {
                const content = document.getElementById('selected-albums-pills');
                const icon = albumsHeader.querySelector('.collapse-icon');

                content.classList.toggle('collapsed');
                icon.classList.toggle('collapsed');
            });
        }
    }

    attachFilterTabListeners() {
        const tabs = document.querySelectorAll('.search-tab');
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                // Update active state
                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');

                // Update filter and re-render
                this.currentSearchFilter = tab.dataset.filter;
                this.renderSearchResults();
            });
        });
    }

    async performSearch(query) {
        const resultsGrid = document.getElementById('search-results-grid');
        // Skeleton rows while waiting
        resultsGrid.innerHTML = Array(4).fill(`
            <div style="display:flex;align-items:center;gap:0.75rem;padding:0.5rem 0;border-bottom:1px solid var(--border-color,#eee)">
                <div class="skeleton" style="width:48px;height:48px;border-radius:50%;flex-shrink:0"></div>
                <div style="flex:1">
                    <div class="skeleton" style="height:14px;width:60%;margin-bottom:6px;border-radius:4px"></div>
                    <div class="skeleton" style="height:12px;width:40%;border-radius:4px"></div>
                </div>
            </div>`).join('');

        try {
            const data = await apiCall(`/api/search?q=${encodeURIComponent(query)}`);
            this.searchResults = data.artists || [];
            this.albumResults = data.albums || [];
            this.renderSearchResults();
        } catch (error) {
            console.error('Search failed:', error);
            resultsGrid.innerHTML = '<div class="error" style="padding:1rem;color:var(--error,#dc3545)">Error al buscar. Inténtalo de nuevo.</div>';
        }
    }

    renderSearchResults() {
        const resultsGrid = document.getElementById('search-results-grid');
        const filterTabs = document.getElementById('search-filter-tabs');

        if (this.searchResults.length === 0 && (!this.albumResults || this.albumResults.length === 0)) {
            resultsGrid.innerHTML = '<div class="no-results">No se encontraron resultados</div>';
            if (filterTabs) filterTabs.style.display = 'none';
            return;
        }

        // Show filter tabs when there are results
        if (filterTabs) filterTabs.style.display = 'flex';

        let html = '';
        const showArtists = this.currentSearchFilter === 'all' || this.currentSearchFilter === 'artists';
        const showAlbums = this.currentSearchFilter === 'all' || this.currentSearchFilter === 'albums';
        const isMobile = window.innerWidth <= 768;

        // Render Artists Section
        if (showArtists && this.searchResults.length > 0) {
            if (this.currentSearchFilter === 'all') {
                html += '<div class="search-section-header">Artistas</div>';
            }

            // Determine how many artists to show
            const artistsToShow = (isMobile && !this.showAllArtists)
                ? this.searchResults.slice(0, 2)
                : this.searchResults;

            html += '<div class="artist-grid">';
            html += artistsToShow.map(artist => {
                const isSelected = this.selectedArtists.some(a => a.name === artist.name);
                const isDisabled = !isSelected && this.selectedArtists.length >= this.options.maxArtists;

                return `
                    <div class="artist-card ${isSelected ? 'selected' : ''} ${isDisabled ? 'disabled' : ''}" 
                         data-artist-name="${artist.name}">
                        <div class="artist-card-content">
                            <div class="artist-image-wrapper">
                                ${artist.image_url
                        ? `<img src="${artist.image_url}" alt="${artist.name}" class="artist-image" />`
                        : `<div class="artist-image-placeholder">🎵</div>`
                    }
                            </div>
                            <div class="artist-info">
                                <div class="artist-name">${artist.name}</div>
                                ${artist.genres && artist.genres.length > 0
                        ? `<div class="artist-genres">${artist.genres.join(', ')}</div>`
                        : ''
                    }
                            </div>
                        </div>
                        <button class="add-artist-btn ${isSelected ? 'added' : ''}" 
                                ${isDisabled ? 'disabled' : ''}
                                data-artist='${JSON.stringify(artist)}'>
                            ${isSelected ? '✓' : '+'}
                        </button>
                    </div>
                `;
            }).join('');
            html += '</div>'; // Close artist-grid

            // Add "Show More" button for mobile if there are more than 2 artists
            if (isMobile && this.searchResults.length > 2) {
                html += `
                    <button class="show-more-btn" id="show-more-artists">
                        ${this.showAllArtists ? 'Ver menos' : `Ver más (${this.searchResults.length - 2} más)`}
                    </button>
                `;
            }
        }

        // Render Albums Section
        if (showAlbums && this.albumResults && this.albumResults.length > 0) {
            if (this.currentSearchFilter === 'all') {
                html += '<div class="search-section-header">Álbumes</div>';
            }

            // Determine how many albums to show
            const albumsToShow = (isMobile && !this.showAllAlbums)
                ? this.albumResults.slice(0, 2)
                : this.albumResults;

            html += '<div class="album-grid">';
            html += albumsToShow.map(album => {
                // HTML-escape the JSON to prevent attribute breaking
                const albumDataEscaped = JSON.stringify(album)
                    .replace(/&/g, '&amp;')
                    .replace(/'/g, '&apos;')
                    .replace(/"/g, '&quot;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;');

                return `
                    <div class="album-card" data-album-title="${album.title}">
                        <div class="album-card-content">
                            <div class="album-image-wrapper">
                                ${album.cover_url
                        ? `<img src="${album.cover_url}" alt="${album.title}" class="album-image" />`
                        : `<div class="album-image-placeholder">💿</div>`
                    }
                            </div>
                            <div class="album-info">
                                <div class="album-title-full">${album.title}</div>
                                <div class="album-artist-full">${album.artist_name || 'Unknown Artist'}</div>
                            </div>
                        </div>
                        <button class="add-album-btn" data-album="${albumDataEscaped}">
                            +
                        </button>
                    </div>
                `;
            }).join('');
            html += '</div>'; // Close album-grid

            // Add "Show More" button for mobile if there are more than 2 albums
            if (isMobile && this.albumResults.length > 2) {
                html += `
                    <button class="show-more-btn" id="show-more-albums">
                        ${this.showAllAlbums ? 'Ver menos' : `Ver más (${this.albumResults.length - 2} más)`}
                    </button>
                `;
            }
        }

        resultsGrid.innerHTML = html;
        this.attachArtistCardListeners();
        this.attachAlbumCardListeners();
        this.attachShowMoreListeners();
    }

    attachShowMoreListeners() {
        const showMoreArtistsBtn = document.getElementById('show-more-artists');
        const showMoreAlbumsBtn = document.getElementById('show-more-albums');

        if (showMoreArtistsBtn) {
            showMoreArtistsBtn.addEventListener('click', () => {
                this.showAllArtists = !this.showAllArtists;
                this.renderSearchResults();
            });
        }

        if (showMoreAlbumsBtn) {
            showMoreAlbumsBtn.addEventListener('click', () => {
                this.showAllAlbums = !this.showAllAlbums;
                this.renderSearchResults();
            });
        }
    }

    attachArtistCardListeners() {
        const artistCards = document.querySelectorAll('.artist-card');

        artistCards.forEach(card => {
            card.addEventListener('click', (e) => {
                // Prevent double triggering if clicking the button directly
                if (e.target.closest('.add-artist-btn')) return;

                const artistName = card.dataset.artistName;
                const btn = card.querySelector('.add-artist-btn');
                if (!btn) return;

                const artist = JSON.parse(btn.dataset.artist);
                const isSelected = this.selectedArtists.some(a => a.name === artist.name);

                if (isSelected) {
                    this.removeArtist(artist.name);
                } else if (this.selectedArtists.length < this.options.maxArtists) {
                    this.addArtist(artist);
                }
            });
        });

        const addButtons = document.querySelectorAll('.add-artist-btn');

        addButtons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const artist = JSON.parse(btn.dataset.artist);
                const isSelected = this.selectedArtists.some(a => a.name === artist.name);

                if (isSelected) {
                    this.removeArtist(artist.name);
                } else if (this.selectedArtists.length < this.options.maxArtists) {
                    this.addArtist(artist);
                }
            });
        });
    }

    attachAlbumCardListeners() {
        const albumCards = document.querySelectorAll('.album-card');

        albumCards.forEach(card => {
            card.addEventListener('click', async (e) => {
                // Prevent double triggering if clicking the button directly
                if (e.target.closest('.add-album-btn')) return;

                const btn = card.querySelector('.add-album-btn');
                if (!btn || btn.disabled) return;

                // Decode HTML entities before parsing JSON
                const albumDataEscaped = btn.dataset.album;
                const albumDataJson = albumDataEscaped
                    .replace(/&quot;/g, '"')
                    .replace(/&apos;/g, "'")
                    .replace(/&lt;/g, '<')
                    .replace(/&gt;/g, '>')
                    .replace(/&amp;/g, '&');
                const album = JSON.parse(albumDataJson);
                await this.addAlbum(album, btn);
            });
        });

        const addButtons = document.querySelectorAll('.add-album-btn');

        addButtons.forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                // Decode HTML entities before parsing JSON
                const albumDataEscaped = btn.dataset.album;
                const albumDataJson = albumDataEscaped
                    .replace(/&quot;/g, '"')
                    .replace(/&apos;/g, "'")
                    .replace(/&lt;/g, '<')
                    .replace(/&gt;/g, '>')
                    .replace(/&amp;/g, '&');
                const album = JSON.parse(albumDataJson);
                await this.addAlbum(album, btn);
            });
        });
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
                    return;
                }
            } catch (error) {
                console.error('Error creating guest user:', error);
                alert('Error al crear usuario. Por favor, recarga la página.');
                return;
            }
        }

        // Disable button and show loading state
        button.disabled = true;
        button.textContent = '⏳';

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

                // Update button to show success permanently
                button.textContent = '✓';
                button.classList.add('album-added');
                button.disabled = true;
                button.style.background = 'var(--primary)';
                button.style.color = 'white';
                button.style.cursor = 'not-allowed';

                // Also mark the card as added
                const albumCard = button.closest('.album-card');
                if (albumCard) {
                    albumCard.classList.add('album-added');
                }

                // Render the selected albums pills
                this.renderSelectedAlbums();
                this.updateContinueButton();
            } else {
                const error = await response.json();
                console.error('Failed to add album:', error);
                alert(`Error al añadir álbum: ${error.detail || 'Error desconocido'}`);
                button.disabled = false;
                button.textContent = '+';
            }
        } catch (error) {
            console.error('Error adding album:', error);
            alert('Error al añadir álbum. Por favor, intenta de nuevo.');
            button.disabled = false;
            button.textContent = '+';
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

    async waitForAllPendingRecommendations() {
        if (this.pendingPromises.size === 0) {
            return;
        }

        console.log(`⏳ Waiting for ${this.pendingPromises.size} pending recommendations to complete...`);
        const allPromises = Array.from(this.pendingPromises.values());
        await Promise.allSettled(allPromises);
        console.log('✓ All pending recommendations completed');
    }

    updateUI() {
        this.renderSelectedArtists();
        this.renderSearchResults();
        this.updateCounter();
        this.updateContinueButton();
        this.options.onSelectionChange(this.selectedArtists);
    }

    renderSelectedArtists() {
        const pillsContainer = document.getElementById('selected-artists-pills');

        if (this.selectedArtists.length === 0) {
            pillsContainer.innerHTML = '<div class="no-selection">Aún no has seleccionado artistas</div>';
            return;
        }

        pillsContainer.innerHTML = this.selectedArtists.map(artist => {
            const isLoading = this.loadingArtists.has(artist.name);
            const cached = this.recommendationsCache[artist.name];
            const hasSuccess = cached && cached.status === 'success';
            const hasError = cached && cached.status === 'error';

            return `
                <div class="artist-pill ${isLoading ? 'loading' : ''} ${hasSuccess ? 'cached' : ''} ${hasError ? 'error' : ''}">
                    ${artist.image_url
                    ? `<img src="${artist.image_url}" alt="${artist.name}" class="pill-image" />`
                    : ''
                }
                    <span class="pill-name">${artist.name}</span>
                    ${isLoading ? '<span class="pill-spinner">⏳</span>' : ''}
                    ${!isLoading && hasSuccess ? '<span class="pill-check">✓</span>' : ''}
                    ${!isLoading && hasError ? '<span class="pill-error" title="${cached.error || 'No se encontraron álbumes'}">⚠</span>' : ''}
                    <button class="pill-remove-btn" data-artist-name="${artist.name}">✕</button>
                </div>
            `;
        }).join('');

        const removeButtons = pillsContainer.querySelectorAll('.pill-remove-btn');
        removeButtons.forEach(btn => {
            btn.addEventListener('click', () => {
                this.removeArtist(btn.dataset.artistName);
            });
        });
    }

    updateCounter() {
        const counter = document.getElementById('artist-counter');
        if (counter) {
            counter.textContent = `${this.selectedArtists.length}/${this.options.maxArtists} seleccionados`;
        }
    }

    updateContinueButton() {
        const continueBtn = document.getElementById('continue-btn');
        if (continueBtn) {
            const isValid = this.isValidSelection();
            const isLoading = this.loadingArtists.size > 0;
            continueBtn.disabled = !isValid || isLoading;

            if (isLoading && isValid) {
                continueBtn.textContent = `Cargando ${this.loadingArtists.size}...`;
            } else {
                continueBtn.textContent = 'Continuar';
            }
        }
    }

    isValidSelection() {
        const totalCount = this.selectedArtists.length + this.selectedAlbums.length;
        return totalCount >= this.options.minArtists &&
            this.selectedArtists.length <= this.options.maxArtists;
    }

    clearSearchResults() {
        const resultsGrid = document.getElementById('search-results-grid');
        const filterTabs = document.getElementById('search-filter-tabs');
        resultsGrid.innerHTML = '';
        this.searchResults = [];
        this.albumResults = [];
        this.currentSearchFilter = 'all';
        this.showAllArtists = false;
        this.showAllAlbums = false;
        if (filterTabs) {
            filterTabs.style.display = 'none';
            // Reset tabs to 'all'
            const tabs = filterTabs.querySelectorAll('.search-tab');
            tabs.forEach(tab => {
                tab.classList.toggle('active', tab.dataset.filter === 'all');
            });
        }
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
}
