// fixture: follows every rule. A comment may mention import { lab } from '$lab/lab.svelte.js' without counting.
import { act, cached } from '$lab/sdk.js';
import Table from '$lab/Table.svelte';
import { helper } from './util.js';
export default {
  id: 'good',
  load: (ctx) => cached(`${ctx.id}:x`, 1000, () => ctx.api.get('/x')),
  objects: (data, ctx) => [{ id: 'good', leaf: ctx.peer('leaf')?.n, maybe: ctx.peer("maybe"), h: helper(), t: Table, a: act }],
};
