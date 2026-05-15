# Vinyl Recommendation System (Vinilogy)

## Overview
This project is a comprehensive vinyl recommendation system that leverages **Spotify and Last.fm listening data** combined with **manual artist selection** and Discogs marketplace information to provide personalized vinyl recommendations. Its main purpose is to help music enthusiasts discover vinyl records based on their digital listening habits, including pricing and local store availability. The business vision is to evolve into a robust, data-rich platform for collectors.

**Key Features:**
- **3 Recommendation Sources**: Spotify, Last.fm, and manual artist-based recommendations
- **Intelligent Merging**: Deduplication across all sources for unique recommendations
- **Dual Scoring Algorithms**: Position-based (Spotify) and playcount-based (Last.fm)

## User Preferences
I want to prioritize a clear, concise, and professional communication style. For development, I prefer an iterative approach, focusing on delivering core functionality first and then enhancing it. I value detailed explanations, especially for complex architectural decisions. Please ask for my approval before making any major changes to the system architecture or core functionalities.

## System Architecture

### UI/UX Decisions
The user interface features a clean, minimalist landing page with dark/light theme support, a "Conectar con Spotify" button, and an OAuth flow. Recommendations are displayed in a responsive grid. Album detail pages are 1400px wide, two-column layouts showing cover art, basic info, Spotify playback, Discogs tracklist, eBay pricing, Discogs marketplace links, and local store links. On-demand pricing and tracklist loading optimize user experience. A fixed progress banner provides non-blocking feedback during recommendation generation. An Admin Interface is available for monitoring, debugging, and real-time request logs, including a real-time CSV import progress panel.

### Technical Implementations
The system uses a microservices architecture built with FastAPI and Python 3.11, employing asynchronous communication with `httpx` and `asyncio.gather`. Shared models ensure data consistency, and structured logging is implemented.

-   **Spotify Integration**: Handles OAuth, retrieves user's top tracks and artists (short/medium/long term), refreshes tokens, and provides album streaming links. Uses position-based scoring algorithm.
-   **Last.fm Integration**: Handles authentication flow (token → user authorization → session key), retrieves user's **top albums directly** via `user.gettopalbums` (simplified approach), with period mapping (7day/3month/12month). Uses cache-first strategy: checks PostgreSQL for existing album data, creates basic DB entries for new albums, and fetches covers from Discogs on-demand only when needed. This approach minimizes API calls and avoids rate limiting.
-   **Discogs Integration**: Normalizes album titles, implements master/release fallback, retrieves tracklists with durations, provides marketplace statistics (prices in EUR), generates sales links, and includes robust rate limiting. It also fetches artist images.
-   **Recommendation Engine**: Dual scoring algorithms (position-based for Spotify, playcount-based for Last.fm), aggregates albums, filters by track count, and boosts scores for favorite artists. It supports background recommendation generation per artist, caching, and intelligent fallbacks, merging Spotify, Last.fm, and artist-based recommendations with advanced deduplication.
-   **Pricing Service**: Finds best prices on eBay (filtered by EU location, converted to EUR, with shipping to Spain) and provides links to specific local vinyl stores.
-   **API Gateway**: Acts as a single entry point, orchestrates workflows, proxies Spotify authentication, and performs microservice health checks.
-   **Optimized Detail Page Flow**: Achieves complete information load (Discogs links, eBay pricing, local stores, tracklists) in 1-2 seconds through parallel fetching.
-   **Last.fm Artist Explorer**: Uses a Discogs-first search for artist images and simplified similar artist retrieval via `artist.getInfo`.
-   **PostgreSQL Caching**: Implements a structured database (artists, albums, similar_artists) with a 7-day expiration for cached data, dramatically improving response times for existing artists. It supports bulk artist import from CSV with persistence of ratings and images.

### System Design Choices
The architecture comprises **six independent microservices**: `Spotify Service` (port 3000), `Discogs Service` (port 3001), `Recommender Service` (port 3002), `Pricing Service` (port 3003), `Last.fm Service` (port 3004), and `API Gateway` (port 5000). This design promotes scalability, maintainability, and clear separation of concerns.

**Time Range Mapping:**
- Spotify: `short_term` (4 weeks), `medium_term` (6 months), `long_term` (1 year)
- Last.fm: `short_term` → `7day`, `medium_term` → `3month`, `long_term` → `12month`

**Scoring Mechanisms:**
- **Spotify**: Position-based with time range boosts (short_term: 3.0x, medium_term: 2.0x, long_term: 1.0x)
- **Last.fm**: Simplified playcount-based system using `user.gettopalbums` directly. Cache-first: checks DB for album data first, only calls Discogs for cover art when creating new album entries.

**Last.fm Optimization (Nov 2025):**
- Uses `user.gettopalbums` endpoint directly instead of `top-artists` → `get albums per artist`
- Cache-first strategy: queries PostgreSQL before external APIs
- Creates basic artist/album DB entries for new discoveries
- Fetches covers from Discogs on-demand (only for cache misses)
- Allows future background jobs to enrich basic entries with full metadata

## External Dependencies

-   **Spotify API**: User authentication (OAuth 2.0), top tracks, top artists with time ranges.
-   **Last.fm API**: User authentication (token-based flow), **top albums** (`user.gettopalbums`) with period filters, playcount data.
-   **Discogs API**: Vinyl release search, marketplace statistics, sales link generation, artist images.
-   **MusicBrainz API**: Artist discographies, studio albums, metadata.
-   **eBay Browse API**: Vinyl record pricing, filtering, currency conversion.
-   **Local Store Integrations**: Direct website links for specific Madrid vinyl shops (Marilians, Bajo el Volcán, Bora Bora, Revolver).
-   **FastAPI**: Python web framework.
-   **httpx**: Asynchronous HTTP client.
-   **PostgreSQL**: Database for caching and persistence.