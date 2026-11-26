<script>
  // A new-password input with the strength hint (the gateway's rule: ≥ 12 characters, not repetitive).
  import { strength } from '$lab/login.js';
  let { value = $bindable(''), id = 'pw', label = 'password', autocomplete = 'new-password' } = $props();
  const s = $derived(strength(value));
</script>

<label class="cap" for={id}>{label}</label>
<input {id} class="field" type="password" bind:value {autocomplete} />
<div class="hint mono" aria-live="polite">
  <span class="track"><span class="fill" class:ok={s.ok && s.bits >= 60} class:warn={s.ok && s.bits < 60} class:bad={!s.ok} style="width:{value ? Math.max(8, Math.min(100, s.score)) : 0}%"></span></span>
  <span class={s.ok ? 'dim' : 'bad'}>{value ? s.label : '≥ 12 characters'}</span>
</div>

<style>
  .hint { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--dim); }
  .track { flex: 1; height: 3px; background: var(--track); border-radius: 2px; overflow: hidden; }
  .fill { display: block; height: 100%; transition: width .2s; }
  .fill.ok { background: var(--ok); } .fill.warn { background: var(--warn); } .fill.bad { background: var(--bad); }
</style>
