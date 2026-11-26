<script>
  import { lazy } from '$lab/sdk.js';
  import { helper } from './util.js';
  let { ctx } = $props();
  const leafCtx = ctx.via('leaf');
  const x = lazy(() => ctx, () => '/x');
</script>
<!-- import { lab } from '$lab/lab.svelte.js' in a comment is fine -->
<p>{helper()} {x.data} {leafCtx?.id}</p>
