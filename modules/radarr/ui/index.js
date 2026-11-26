// radarr — Radarr in lab: queue, stuck downloads (remove, manual import), wanted, calendar, health, the movie library
// (search, interactive search, edit, delete). The UI is the SDK's shared *arr module ($lab/arr/, shared with sonarr);
// the Media view combining it with the rest of the stack lives in module arr.
import { createArr } from '$lab/arr/arr.js';

export default createArr('radarr');
