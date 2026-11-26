// v1: not checked until it moves to "manifest": 2
import { lab } from '$lab/lab.svelte.js';
import { helper } from '../../good/ui/util.js';
export default { id: 'legacy', load: (ctx) => [lab.now, helper(), ctx.peer('anything')] };
