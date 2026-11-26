<script>
  // Safe markdown (see md.js): elements only, no {@html}; links only http(s) via safeUrl, opened in a new tab.
  import { parse } from './md.js';
  import { safeUrl } from '$lab/sdk.js';
  let { text = '' } = $props();
  const blocks = $derived(parse(text));
</script>

{#snippet line(parts)}
  {#each parts as x}
    {#if x.t === 'code'}<code>{x.v}</code>
    {:else if x.t === 'b'}<strong>{x.v}</strong>
    {:else if x.t === 'i'}<em>{x.v}</em>
    {:else if x.t === 'a'}{@const href = safeUrl(x.href)}{#if href}<a {href} target="_blank" rel="noopener noreferrer">{x.v}</a>{:else}{x.v}{/if}
    {:else}{x.v}{/if}
  {/each}
{/snippet}

<div class="md">
  {#each blocks as b}
    {#if b.t === 'p'}<p>{@render line(b.v)}</p>
    {:else if b.t === 'h'}<p class="h mono">{@render line(b.v)}</p>
    {:else if b.t === 'ul'}<ul>{#each b.items as it}<li>{@render line(it)}</li>{/each}</ul>
    {:else if b.t === 'ol'}<ol>{#each b.items as it}<li>{@render line(it)}</li>{/each}</ol>
    {:else if b.t === 'code'}<pre class="mono">{b.v}</pre>
    {:else if b.t === 'quote'}<blockquote>{@render line(b.v)}</blockquote>
    {:else if b.t === 'table'}
      <div class="tw"><table><tbody>
        {#each b.rows as r, n}<tr class:th={n === 0}>{#each r as c}<td>{@render line(c)}</td>{/each}</tr>{/each}
      </tbody></table></div>
    {/if}
  {/each}
</div>

<style>
  .md { font-size: 13.5px; line-height: 1.55; overflow-wrap: anywhere; }
  .md :global(p) { margin: 0 0 7px; white-space: pre-line; }
  .h { font-size: 12px; color: var(--sig); margin-top: 10px !important; }
  ul, ol { margin: 0 0 7px; padding-left: 18px; }
  li { margin: 1px 0; }
  code { font-family: "Geist Mono Variable", monospace; font-size: 12px; background: var(--q); border: 1px solid var(--line); border-radius: 3px; padding: 0 4px; }
  pre { font-size: 11.5px; background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 8px 10px; overflow-x: auto; margin: 0 0 8px; white-space: pre; }
  blockquote { margin: 0 0 7px; padding-left: 10px; border-left: 2px solid var(--sig); color: var(--dim); }
  .tw { overflow-x: auto; margin-bottom: 8px; }
  table { border-collapse: collapse; font-size: 12px; }
  td { padding: 3px 9px; border-bottom: 1px solid var(--line); white-space: nowrap; }
  .th td { color: var(--dim); font-family: "Geist Mono Variable", monospace; font-size: 11px; }
  a { overflow-wrap: anywhere; }
</style>
