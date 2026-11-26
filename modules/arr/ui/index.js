// arr — the media hub: no backend of its own. Its view and tiles read the data the media modules already loaded
// (ctx.peer: sonarr / radarr / prowlarr / bazarr / qbit / jellyfin / seerr, all optional) and act through each
// module's own ctx (ctx.via), so every click is checked against THAT module's manifest.
import MediaView from './MediaView.svelte';
import QueueTile from './QueueTile.svelte';
import UpcomingTile from './UpcomingTile.svelte';

export default {
  id: 'arr',
  load: () => ({ at: Date.now() }),
  views: [{ id: 'media', label: 'Media', icon: 'play', component: MediaView, min: 'admin' }],
  tiles: [
    { id: 'queue', label: 'media queue', w: 4, h: 2, component: QueueTile, min: 'admin' },
    { id: 'upcoming', label: 'upcoming', w: 4, h: 2, component: UpcomingTile, min: 'admin' },
  ],
};
