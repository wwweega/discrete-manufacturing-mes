<script setup>
defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: '-' },
  unit: { type: String, default: '' },
  desc: { type: String, default: '' },
  tone: { type: String, default: 'primary' }
})
</script>

<template>
  <div class="card" style="margin-bottom: 0">
    <div class="muted small">{{ label }}</div>
    <div style="font-size: 24px; font-weight: 600; margin: 4px 0 2px">
      <span :class="`tag-${tone}`" style="background: transparent; padding: 0">{{ value }}</span>
      <span class="small muted" style="font-weight: 400"> {{ unit }}</span>
    </div>
    <div class="muted small">{{ desc }}</div>
  </div>
</template>
