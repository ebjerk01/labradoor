<script>
  // Seerr permission bit mask as grouped checkboxes. `identity` = show the owner-only group (admin/users/settings).
  import { PERM_GROUPS } from './sr.js';
  let { value = $bindable(0), perms, identity = true, disabled = false } = $props();
  const on = (k) => (value & perms[k]) !== 0;
  const flip = (k, v) => { value = v ? value | perms[k] : value & ~perms[k]; };
  const isAdmin = $derived((value & (perms?.ADMIN || 0)) !== 0);
</script>

<div class="pe">
  {#each PERM_GROUPS.filter((g) => identity || !g.owner) as g (g.label)}
    <fieldset disabled={disabled || (isAdmin && !g.owner)}>
      <legend class="cap">{g.label}</legend>
      {#each g.bits as [k, label] (k)}
        <label class="mono"><input type="checkbox" checked={on(k)} onchange={(e) => flip(k, e.currentTarget.checked)} /> {label}</label>
      {/each}
    </fieldset>
  {/each}
  {#if isAdmin}<span class="mono dim s">admin implies every permission</span>{/if}
</div>

<style>
  .pe { display: flex; flex-wrap: wrap; gap: 10px 18px; }
  fieldset { border: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; min-width: 120px; }
  fieldset:disabled { opacity: .5; }
  legend { padding: 0 0 3px; }
  label { font-size: 11.5px; display: flex; gap: 5px; align-items: center; }
  .s { font-size: 11px; width: 100%; }
</style>
