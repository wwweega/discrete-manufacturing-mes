<script setup>
/** 状态标签：按 tone 渲染语义色。 */
defineProps({
  map: { type: Object, required: true },
  value: { type: String, default: '' }
})
</script>

<template>
  <span class="tag" :class="`tag-${map[value]?.tone || 'muted'}`">
    {{ map[value]?.label || value || '-' }}
  </span>
</template>
