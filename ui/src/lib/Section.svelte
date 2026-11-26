<script>
  // A facet / panel section: "~/title" left, module tag right.
  let { title, src = '', children } = $props();
</script>

<section class="sec">
  <div class="head"><span class="cap">{title}</span>{#if src}<span class="mono src">{src}</span>{/if}</div>
  {@render children?.()}
</section>

<style>
  .sec { padding: 14px 20px; border-bottom: 1px solid var(--line); display: flex; flex-direction: column; gap: 10px; }
  .head { display: flex; justify-content: space-between; align-items: baseline; }
  .src { font-size: 10.5px; color: var(--sig); }
</style>
