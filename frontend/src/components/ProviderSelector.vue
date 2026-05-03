<template>
  <label class="provider-selector">
    <span>Provider</span>
    <select :value="modelValue" @change="selectProvider($event.target.value)">
      <option v-for="provider in providers" :key="provider.name" :value="provider.name" :disabled="!provider.available">
        {{ labelFor(provider) }}
      </option>
    </select>
    <small v-if="error">{{ error }}</small>
  </label>
</template>

<script setup>
import { onMounted, ref } from 'vue'

defineProps({
  modelValue: {
    type: String,
    required: true,
  },
})

const emit = defineEmits(['update:modelValue'])

const providers = ref([{ name: 'ollama', available: true, default: true }])
const error = ref('')

function labelFor(provider) {
  const suffix = provider.available ? '' : ' (disabled)'
  return `${provider.name}${provider.default ? ' (default)' : ''}${suffix}`
}

async function selectProvider(provider) {
  error.value = ''
  const response = await fetch('/api/system/provider', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ provider }),
  })
  const data = await response.json()
  if (!response.ok) {
    error.value = data.detail || 'Provider switch failed'
    return
  }
  providers.value = data.providers
  const selected = data.providers.find((item) => item.selected)
  emit('update:modelValue', selected?.name || provider)
}

onMounted(async () => {
  const response = await fetch('/api/system/providers', { credentials: 'include' })
  if (response.ok) {
    const data = await response.json()
    providers.value = data.providers
    const selected = data.providers.find((item) => item.selected)
    if (selected) emit('update:modelValue', selected.name)
  }
})
</script>
