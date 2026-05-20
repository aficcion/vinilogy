
// Discogs Journey Wizard Logic

const DiscogsWizard = {
    state: {
        step: 0,
        stats: null,
        topArtists: [],
        selectedArtists: [],
        showAllArtists: false,
        strategies: ["complete", "upgrade"], // Default both
        generating: false
    },

    init: async function () {
        // Create modal container if not exists
        if (!document.getElementById('wizard-modal')) {
            this.createModal();
        }
    },

    launch: async function (force = false) {
        if (!force && localStorage.getItem('discogs_wizard_completed') === 'true') {
            console.log("Wizard already completed.");
            return;
        }
        this.resetState();
        this.showModal();
        await this.loadStats();
    },

    resetState: function () {
        this.state = {
            step: 1,
            stats: null,
            topArtists: [],
            selectedArtists: [],
            showAllArtists: false,
            strategies: ["complete", "upgrade"],
            generating: false
        };
        // Do NOT call renderStep here, wait for loadStats
    },

    createModal: function () {
        const modal = document.createElement('div');
        modal.id = 'wizard-modal';
        modal.className = 'modal-overlay hidden';
        modal.innerHTML = `
            <div class="modal-content wizard-container">
                <button class="close-btn" onclick="DiscogsWizard.close()">&times;</button>
                <div id="wizard-body">
                    <!-- Dynamic Content -->
                </div>
            </div>
        `;
        document.body.appendChild(modal);
    },

    showModal: function () {
        const modal = document.getElementById('wizard-modal');
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    },

    close: function () {
        const modal = document.getElementById('wizard-modal');
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    },

    waitForSync: function () {
        if (this.syncInterval) clearInterval(this.syncInterval);
        const userId = localStorage.getItem('userId');
        console.log('[Wizard] Starting sync polling for user', userId);

        this.syncInterval = setInterval(async () => {
            try {
                const resp = await fetch(`/user/${userId}/sync-status`);
                if (!resp.ok) return;
                const data = await resp.json();

                console.log('[Wizard] Poll status:', data.status, data.processed);

                if (data.status === 'completed') {
                    clearInterval(this.syncInterval);
                    this.syncInterval = null;
                    this.loadStats(); // Retry loading stats
                } else if (data.status === 'failed') {
                    clearInterval(this.syncInterval);
                    this.syncInterval = null;
                    this.renderError("La sincronización falló: " + data.message);
                } else {
                    // Update count
                    const p = document.getElementById('wizard-sync-count');
                    if (p) p.innerHTML = `<strong>${data.processed} ítems procesados...</strong>`;
                }
            } catch (e) { console.warn(e); }
        }, 2000);
    },

    loadStats: async function () {
        this.renderLoading("Comprobando estado...");
        const userId = localStorage.getItem('userId');
        const username = localStorage.getItem('discogs_username');

        // 1. Check Sync Status
        try {
            const statusResp = await fetch(`/user/${userId}/sync-status`);
            if (statusResp.ok) {
                const statusData = await statusResp.json();
                console.log('[Wizard] loadStats status:', statusData);

                if (statusData.status === 'running') {
                    this.renderWait(statusData.processed);
                    this.waitForSync();
                    return;
                }

                // Clear any polling if we are here (completed/idle)
                if (this.syncInterval) {
                    clearInterval(this.syncInterval);
                    this.syncInterval = null;
                }
            }
        } catch (e) {
            console.warn("Could not check sync status", e);
        }

        this.renderLoading("Analizando tu colección...");

        try {
            const resp = await fetch('/api/collection/stats', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: parseInt(userId), username: username })
            });

            if (resp.ok) {
                const data = await resp.json();
                console.log('[Wizard] Stats loaded:', data);
                this.state.stats = data;

                // Filter "Various" / "Varios" artists
                const rawArtists = data.top_artists || [];
                this.state.topArtists = rawArtists.filter(a => !a.name.match(/^(various|varios)( artists| artistas)?$/i));

                // Auto-select TOP 5
                this.state.selectedArtists = this.state.topArtists.slice(0, 5).map(a => a.name);
                this.state.step = 1; // Go to Step 1 (Stats View)
                this.renderStep();
            } else {
                this.renderError("Error cargando estadísticas.");
            }
        } catch (e) {
            console.error(e);
            this.renderError("Error de conexión.");
        }
    },

    renderLoading: function (msg) {
        const body = document.getElementById('wizard-body');
        body.innerHTML = `
            <div class="wizard-step centered">
                <div class="spinner"></div>
                <h2>${msg}</h2>
            </div>
        `;
    },

    renderWait: function (processed) {
        const body = document.getElementById('wizard-body');
        body.innerHTML = `
            <div class="wizard-step centered">
                <div class="spinner"></div>
                <h2>Sincronizando Colección</h2>
                <p>Estamos importando tus datos de Discogs.</p>
                <p id="wizard-sync-count"><strong>${processed || 0} ítems procesados...</strong></p>
                <p class="subtitle">Por favor espera un momento...</p>
                <button onclick="DiscogsWizard.close()" class="btn-secondary">Cerrar</button>
            </div>
        `;
    },

    renderError: function (msg) {
        const body = document.getElementById('wizard-body');
        body.innerHTML = `
            <div class="wizard-step centered">
                <h2>⚠️ Ops</h2>
                <p>${msg}</p>
                <button onclick="DiscogsWizard.close()" class="btn-secondary">Cerrar</button>
            </div>
        `;
    },

    renderStep: function () {
        const step = this.state.step;
        const body = document.getElementById('wizard-body');

        if (step === 1) {
            // Safety check for stats
            if (!this.state.stats) {
                this.renderLoading("Cargando datos...");
                return;
            }

            // STEP 1: STATS & STRATEGY
            // Show big numbers and Strategy selection
            body.innerHTML = `
                <div class="wizard-step">
                    <h2>Tu Colección en Números</h2>
                    <div class="stats-grid">
                        <div class="stat-card">
                            <span class="stat-number">${this.state.stats.total_items}</span>
                            <span class="stat-label">Ítems Totales</span>
                        </div>
                        <div class="stat-card">
                            <span class="stat-number">${this.state.topArtists.length}</span>
                            <span class="stat-label">Artistas Recurrentes</span>
                        </div>
                    </div>
                    
                    <h3>¿Qué objetivo tienes?</h3>
                    <div class="strategy-selector">
                        <label class="strategy-option ${this.state.strategies.includes('complete') ? 'selected' : ''}">
                            <input type="checkbox" ${this.state.strategies.includes('complete') ? 'checked' : ''} onchange="DiscogsWizard.toggleStrategy('complete', this.checked)">
                            <div class="icon-box"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path></svg></div>
                            <div>
                                <strong>Completar Discografías</strong>
                                <small>Busca álbumes clave que te faltan de tus artistas favoritos.</small>
                            </div>
                        </label>
                         <label class="strategy-option ${this.state.strategies.includes('upgrade') ? 'selected' : ''}">
                            <input type="checkbox" ${this.state.strategies.includes('upgrade') ? 'checked' : ''} onchange="DiscogsWizard.toggleStrategy('upgrade', this.checked)">
                             <div class="icon-box"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg></div>
                            <div>
                                <strong>Mejorar Formato (Upgrade)</strong>
                                <small>Te avisa si un disco que tienes en CD/Digital existe en Vinilo.</small>
                            </div>
                        </label>
                    </div>

                    <div class="wizard-footer">
                        <button class="btn-primary full-width" onclick="DiscogsWizard.nextStep()">Continuar</button>
                    </div>
                </div>
            `;
        } else if (step === 2) {
            // STEP 2: ARTIST SELECTION
            // Show list of Top Artists
            const limit = this.state.showAllArtists ? this.state.topArtists.length : 10;
            const visibleArtists = this.state.topArtists.slice(0, limit);

            const listHtml = visibleArtists.map(artist => `
                <label class="artist-checkbox-row">
                    <input type="checkbox" 
                           value="${artist.name}" 
                           ${this.state.selectedArtists.includes(artist.name) ? 'checked' : ''}
                           onchange="DiscogsWizard.toggleArtist('${artist.name}', this.checked)">
                    <span class="artist-name">${artist.name}</span>
                    <span class="artist-count">(${artist.count})</span>
                </label>
            `).join('');

            body.innerHTML = `
                <div class="wizard-step">
                    <h2>Selecciona tus Artistas</h2>
                    <p class="subtitle">Hemos detectado estos artistas frecuentes. Selecciona los que quieras priorizar.</p>
                    
                    <div class="artist-list-container">
                        ${listHtml}
                    </div>
                    
                    ${!this.state.showAllArtists && this.state.topArtists.length > 10 ?
                    `<button class="btn-text" onclick="DiscogsWizard.showMore()">Ver todos (${this.state.topArtists.length})</button>` : ''}

                    <div class="wizard-footer">
                        <button class="btn-secondary" onclick="DiscogsWizard.prevStep()">Atrás</button>
                        <button class="btn-primary" onclick="DiscogsWizard.finish()">Generar Recomendaciones</button>
                    </div>
                </div>
            `;
        } else if (step === 3) {
            // STEP 3: GENERATING
            this.renderLoading("Generando tu colección personalizada...");
        }
    },

    toggleStrategy: function (strategy, checked) {
        if (checked) {
            if (!this.state.strategies.includes(strategy)) this.state.strategies.push(strategy);
        } else {
            this.state.strategies = this.state.strategies.filter(s => s !== strategy);
        }
        // Re-render to update classes if needed, or just toggle class manually
        this.renderStep();
    },

    nextStep: function () {
        if (this.state.strategies.length === 0) {
            alert("Por favor selecciona al menos una estrategia.");
            return;
        }
        this.state.step++;
        this.renderStep();
    },

    toggleArtist: function (name, checked) {
        if (checked) {
            if (!this.state.selectedArtists.includes(name)) this.state.selectedArtists.push(name);
        } else {
            this.state.selectedArtists = this.state.selectedArtists.filter(n => n !== name);
        }
        // Update counter without full re-render
        const countSpan = document.querySelector('.selection-count');
        if (countSpan) countSpan.textContent = `${this.state.selectedArtists.length} seleccionados`;
    },

    showMore: function () {
        this.state.showAllArtists = true;
        this.renderStep();
    },

    finish: async function () {
        if (this.state.selectedArtists.length === 0) {
            alert("Selecciona al menos un artista.");
            return;
        }

        this.state.step = 3;
        this.renderStep();

        const userId = localStorage.getItem('userId');

        // 1. Save Preferences
        try {
            await fetch('/api/collection/preferences', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_id: parseInt(userId),
                    focus_artists: this.state.selectedArtists,
                    strategies: this.state.strategies
                })
            });

            // 2. Generate
            const resp = await fetch('/api/collection/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_id: parseInt(userId),
                    focus_artists: this.state.selectedArtists,
                    strategies: this.state.strategies
                })
            });

            if (resp.ok) {
                const data = await resp.json();
                this.complete(data);
            } else {
                this.renderError("Error generando recomendaciones.");
            }

        } catch (e) {
            console.error(e);
            this.renderError("Error en el proceso final.");
        }
    },

    complete: function (data) {
        localStorage.setItem('discogs_wizard_completed', 'true');
        const count = data.generated || 0;
        const saved = data.saved || 0;

        const body = document.getElementById('wizard-body');
        body.innerHTML = `
            <div class="wizard-step centered">
                <div style="margin-bottom:1rem; color: var(--success-color);">
                    <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
                </div>
                <h2>¡Todo listo!</h2>
                <p>Hemos generado <strong>${count}</strong> recomendaciones personalizadas.</p>
                ${saved > 0 ? `<p class="subtitle">Se han guardado ${saved} nuevas en tu perfil.</p>` : ''}
                
                <button class="btn-primary" onclick="DiscogsWizard.closeAndRefresh()">Ver Recomendaciones</button>
            </div>
        `;
    },

    closeAndRefresh: function () {
        this.close();
        window.location.reload(); // Simple reload to fetch new recs
    }
};

// Auto-init on load if needed, but better called by app-user.js
