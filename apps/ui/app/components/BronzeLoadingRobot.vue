<script setup lang="ts">
withDefaults(defineProps<{ phase?: string }>(), { phase: 'Préparation du chargement…' })
</script>

<template>
  <div class="rounded-xl border border-default bg-elevated/30 p-6 text-center" role="status" aria-live="polite" aria-busy="true">
    <svg viewBox="0 0 760 280" class="mx-auto w-full max-w-3xl" aria-hidden="true">
      <path d="M30 238H730" stroke="var(--ui-border-accented)" stroke-width="2" />
      <rect x="65" y="182" width="255" height="28" rx="14" fill="var(--ui-bg-accented)" stroke="var(--ui-border-accented)" />
      <g class="belt"><path v-for="x in 12" :key="x" :d="`M${55+x*22} 188v16`" stroke="var(--ui-text-dimmed)" stroke-width="3" /></g>
      <path d="M90 210v28m205-28v28" stroke="var(--ui-text-dimmed)" stroke-width="8" />
      <g class="processed"><rect v-for="y in 5" :key="y" x="270" :y="179-y*4" width="38" height="4" rx="1" fill="var(--ui-bg)" stroke="var(--ui-border-accented)" /></g>
      <path d="M300 167h150v12H300zm15 12v59m120-59v59" fill="var(--ui-bg-accented)" stroke="var(--ui-border-accented)" stroke-width="3" />
      <rect x="318" y="130" width="101" height="35" rx="7" fill="var(--ui-bg)" stroke="var(--ui-text-dimmed)" stroke-width="3" />
      <rect x="328" y="123" width="81" height="11" rx="3" fill="var(--ui-bg-accented)" stroke="var(--ui-border-accented)" />
      <rect class="scanner" x="335" y="119" width="6" height="16" rx="2" fill="var(--ui-primary)" />
      <circle cx="404" cy="148" r="3" fill="var(--ui-primary)" />
      <g class="sheet"><rect x="330" y="149" width="45" height="5" rx="1" fill="var(--ui-bg)" stroke="var(--ui-border-accented)" /></g>
      <g v-for="(pile,index) in [{x:605,y:213,r:-9},{x:658,y:219,r:12},{x:566,y:226,r:-18}]" :key="index" :transform="`translate(${pile.x} ${pile.y}) rotate(${pile.r})`">
        <rect v-for="n in 7" :key="n" :x="(n%3)*3" :y="-n*4" width="49" height="5" rx="1" fill="var(--ui-bg)" stroke="var(--ui-border-accented)" />
      </g>
      <g class="robot">
        <ellipse cx="0" cy="235" rx="35" ry="5" fill="var(--ui-border)" opacity=".6" />
        <path d="M-16 211v13m32-13v13" stroke="var(--ui-text-dimmed)" stroke-width="9" stroke-linecap="round" />
        <circle cx="-16" cy="229" r="8" fill="var(--ui-text-muted)" /><circle cx="16" cy="229" r="8" fill="var(--ui-text-muted)" />
        <rect x="-27" y="171" width="54" height="42" rx="12" fill="var(--ui-primary)" />
        <rect x="-31" y="123" width="62" height="45" rx="14" fill="var(--ui-bg)" stroke="var(--ui-primary)" stroke-width="3" />
        <path d="M0 121v-10" stroke="var(--ui-primary)" stroke-width="3" /><circle cx="0" cy="108" r="5" fill="var(--ui-primary)" />
        <rect x="-23" y="133" width="46" height="23" rx="8" fill="var(--ui-bg-inverted)" />
        <circle cx="-11" cy="143" r="3" fill="var(--ui-primary)" /><circle cx="11" cy="143" r="3" fill="var(--ui-primary)" />
        <path d="M-5 151q5 4 10 0" fill="none" stroke="var(--ui-primary)" stroke-width="2" />
        <path d="M-28 183l-12 13m68-13 12 13" stroke="var(--ui-primary)" stroke-width="8" stroke-linecap="round" />
        <g class="carried"><rect v-for="n in 6" :key="n" x="-24" :y="193-n*4" width="48" height="5" rx="1" fill="var(--ui-bg)" stroke="var(--ui-border-accented)" /></g>
      </g>
    </svg>
    <p class="mt-3 font-medium text-highlighted">{{ phase }}</p>
  </div>
</template>

<style scoped>
.robot { animation: robot-trip 9s ease-in-out infinite; }
.carried { animation: carry 9s ease-in-out infinite; }
.scanner { animation: scan 9s linear infinite; }
.sheet { animation: sheet-out 9s ease-in-out infinite; }
.processed { animation: paper-belt 9s linear infinite; }
.belt { animation: belt 0.8s linear infinite; }
@keyframes robot-trip { 0%,8% { transform:translateX(470px) } 36%,45% { transform:translateX(590px) } 72%,100% { transform:translateX(470px) } }
@keyframes carry { 0%,42% { opacity:0; transform:translate(0,0) } 43%,72% { opacity:1; transform:translate(0,0) } 78% { opacity:1; transform:translate(-94px,-56px) } 79%,100% { opacity:0; transform:translate(-94px,-56px) } }
@keyframes scan { 0%,78%,100% { opacity:0; transform:translateX(0) } 79% { opacity:1; transform:translateX(0) } 90% { opacity:1; transform:translateX(65px) } 95% { opacity:0; transform:translateX(65px) } }
@keyframes sheet-out { 0%,90% { opacity:0; transform:translate(0,0) } 91% { opacity:1; transform:translate(0,0) } 100% { opacity:1; transform:translate(-45px,23px) } }
@keyframes paper-belt { 0%,85% { opacity:0; transform:translateX(0) } 86% { opacity:1; transform:translateX(0) } 100% { opacity:0; transform:translateX(-180px) } }
@keyframes belt { to { transform:translateX(-22px) } }
@media (prefers-reduced-motion: reduce) { .robot { animation:none; transform:translateX(470px) } .carried,.scanner,.sheet,.processed,.belt { animation:none } .scanner,.sheet,.processed { opacity:0 } }
</style>
