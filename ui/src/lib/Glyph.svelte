<script>
  // Status = shape + colour: ● ok ▲ warn ■ fault ○ off
  import { GLYPH, statusVar } from './fmt.js';
  let { status = 'unknown', size = 11 } = $props();
</script>

<span class="mono" style:color={statusVar(status)} style:font-size="{size}px" title={status}>{GLYPH[status] || '·'}</span>
