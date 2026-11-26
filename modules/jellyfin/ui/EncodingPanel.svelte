<script>
  // Transcoding + hardware acceleration: the settings that matter, edited in place (Jellyfin stores the whole section, so
  // the rest is sent back unchanged; the encoder binary path is never sent — Jellyfin only takes that from its own config).
  import { lazy } from '$lab/sdk.js';
  import { write } from './store.svelte.js';
  let { ctx } = $props();

  const cfg = lazy(() => ctx, () => '/System/Configuration/encoding');
  const can = $derived(ctx.can('POST', '/System/Configuration/encoding') !== 'no');
  let ed = $state(null);
  let base = '';
  $effect.pre(() => {
    const c = cfg.data;
    if (c && JSON.stringify(c) !== base) { base = JSON.stringify(c); ed = JSON.parse(base); }
  });
  const dirty = $derived(ed && JSON.stringify(ed) !== base);
  const HW = ['none', 'nvenc', 'qsv', 'vaapi', 'amf', 'v4l2m2m', 'rkmpp', 'videotoolbox'];
  const CODECS = ['h264', 'hevc', 'mpeg2video', 'mpeg4', 'vc1', 'vp8', 'vp9', 'av1'];
  const PRESETS = ['auto', 'veryslow', 'slower', 'slow', 'medium', 'fast', 'faster', 'veryfast', 'superfast', 'ultrafast'];
  const TONE = ['none', 'clip', 'linear', 'gamma', 'reinhard', 'hable', 'mobius', 'bt2390'];
  const FLAGS = [
    ['EnableHardwareEncoding', 'hardware encoding'], ['AllowHevcEncoding', 'allow HEVC encoding'], ['AllowAv1Encoding', 'allow AV1 encoding'],
    ['EnableDecodingColorDepth10Hevc', '10-bit HEVC decode'], ['EnableDecodingColorDepth10Vp9', '10-bit VP9 decode'],
    ['EnableDecodingColorDepth10HevcRext', 'HEVC RExt 10-bit decode'], ['EnableDecodingColorDepth12HevcRext', 'HEVC RExt 12-bit decode'],
    ['EnableEnhancedNvdecDecoder', 'enhanced NVDEC'], ['PreferSystemNativeHwDecoder', 'prefer native hw decoder'],
    ['EnableTonemapping', 'tone mapping (HDR → SDR)'], ['EnableThrottling', 'throttle transcodes'], ['EnableSegmentDeletion', 'delete old segments'],
    ['EnableSubtitleExtraction', 'extract subtitles on the fly'], ['DeinterlaceDoubleRate', 'double-rate deinterlace'],
  ];
  function codec(c, on) { ed.HardwareDecodingCodecs = on ? [...new Set([...(ed.HardwareDecodingCodecs || []), c])] : (ed.HardwareDecodingCodecs || []).filter((x) => x !== c); }
  async function save() {
    const { EncoderAppPath, ...body } = ed;  // eslint-disable-line no-unused-vars
    if (await write(ctx, [], { path: '/System/Configuration/encoding', body, label: 'jellyfin: transcoding settings' })) cfg.reload();
  }
</script>

{#if cfg.error}<p class="mono bad s">{cfg.error}</p>
{:else if !ed}<p class="mono dim spin s">loading</p>
{:else}
  <fieldset class="enc" disabled={!can}>
    <div class="grid">
      <label class="mono">acceleration <select class="field" bind:value={ed.HardwareAccelerationType}>{#each HW as h}<option value={h}>{h}</option>{/each}</select></label>
      {#if ed.HardwareAccelerationType === 'vaapi'}<label class="mono">VA-API device <input class="field" bind:value={ed.VaapiDevice} /></label>{/if}
      {#if ed.HardwareAccelerationType === 'qsv'}<label class="mono">QSV device <input class="field" bind:value={ed.QsvDevice} /></label>{/if}
      <label class="mono">threads <input class="field n" type="number" min="-1" max="64" bind:value={ed.EncodingThreadCount} /> <span class="dim">-1 auto</span></label>
      <label class="mono">preset <select class="field" bind:value={ed.EncoderPreset}>{#each PRESETS as p}<option value={p}>{p}</option>{/each}</select></label>
      <label class="mono">CRF h264 <input class="field n" type="number" min="0" max="51" bind:value={ed.H264Crf} /> h265 <input class="field n" type="number" min="0" max="51" bind:value={ed.H265Crf} /></label>
      <label class="mono">tone mapping <select class="field" bind:value={ed.TonemappingAlgorithm}>{#each TONE as t}<option value={t}>{t}</option>{/each}</select></label>
      <label class="mono">throttle after <input class="field n" type="number" min="0" bind:value={ed.ThrottleDelaySeconds} /> s</label>
      <label class="mono">keep segments <input class="field n" type="number" min="0" bind:value={ed.SegmentKeepSeconds} /> s</label>
      <label class="mono">deinterlace <select class="field" bind:value={ed.DeinterlaceMethod}><option value="yadif">yadif</option><option value="bwdif">bwdif</option></select></label>
      <label class="mono wide">transcode temp <input class="field path" bind:value={ed.TranscodingTempPath} /></label>
    </div>
    <div class="cap">hardware decoding</div>
    <div class="flags">{#each CODECS as c}<label class="mono"><input type="checkbox" checked={(ed.HardwareDecodingCodecs || []).includes(c)} onchange={(e) => codec(c, e.currentTarget.checked)} /> {c}</label>{/each}</div>
    <div class="flags">{#each FLAGS as [k, l] (k)}<label class="mono"><input type="checkbox" bind:checked={ed[k]} /> {l}</label>{/each}</div>
    <span class="mono dim s">encoder: {ed.EncoderAppPathDisplay || '–'} (set on {ctx.settings?.host || 'the server'} only)</span>
    <div class="row">
      <button class="btn" class:primary={dirty} disabled={!dirty} onclick={save}>save</button>
      {#if dirty}<button class="btn" onclick={() => (ed = JSON.parse(base))}>undo</button>{/if}
      <span class="mono dim s">new transcodes use it; running ones keep their settings</span>
    </div>
  </fieldset>
{/if}

<style>
  .enc { border: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 10px; min-width: 0; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 6px 16px; }
  label { font-size: 11.5px; display: flex; align-items: center; gap: 6px; }
  .wide { grid-column: 1 / -1; }
  .flags { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 2px 12px; }
  .field { background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 4px 7px; font-size: 12px; color: var(--ink); min-width: 0; }
  .n { width: 64px; }
  .path { flex: 1; }
  .row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .s { font-size: 10.5px; }
  .bad { color: var(--bad); }
</style>
