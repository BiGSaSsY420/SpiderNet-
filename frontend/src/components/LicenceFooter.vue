<template>
  <footer class="licence">
    <div class="mf-container licence__inner">
      <p class="licence__text">
        SpiderNet is free software under the
        <a href="https://www.gnu.org/licenses/agpl-3.0.html"
           target="_blank" rel="noopener noreferrer">AGPL-3.0</a>,
        modified from
        <a :href="upstreamUrl" target="_blank" rel="noopener noreferrer">MiroFish</a>.
      </p>
      <p class="licence__text">
        <!-- AGPL section 13: everyone using this over a network is entitled to
             the source of the exact version they are using. -->
        <a :href="sourceLink" target="_blank" rel="noopener noreferrer">
          Get the source of this version
        </a>
        <span v-if="shortRevision" class="licence__rev mf-mono">{{ shortRevision }}</span>
      </p>
    </div>
  </footer>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getSource } from '../api/legal'

const info = ref(null)

const upstreamUrl = computed(() =>
  info.value?.upstream_url || 'https://github.com/666ghj/MiroFish'
)

const sourceLink = computed(() =>
  info.value?.revision_url || info.value?.source_url ||
  'https://github.com/BiGSaSsY420/SpiderNet-'
)

const shortRevision = computed(() => {
  const rev = info.value?.revision
  return rev && rev !== 'unknown' ? rev.slice(0, 7) : ''
})

onMounted(async () => {
  try {
    info.value = (await getSource()).data
  } catch {
    // The links fall back to sensible defaults, so a failed lookup still
    // leaves a working offer rather than a dead footer.
  }
})
</script>

<style scoped>
.licence {
  border-top: 1px solid var(--mf-separator);
  padding: var(--mf-space-5) 0 var(--mf-space-7);
  margin-top: var(--mf-space-8);
}

.licence__inner {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--mf-space-4);
  flex-wrap: wrap;
}

.licence__text {
  font-size: var(--mf-text-sm);
  color: var(--mf-ink-muted);
}

.licence__rev {
  margin-left: var(--mf-space-2);
  font-size: var(--mf-text-xs);
  color: var(--mf-ink-faint);
}
</style>
