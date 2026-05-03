<template>
  <section class="chat-box">
    <div class="messages" aria-live="polite">
      <article v-for="message in messages" :key="message.id" :class="['message', message.role]">
        <strong>{{ message.role }}</strong>
        <p>{{ message.content }}</p>
        <small v-if="message.external">External provider: {{ message.provider }}</small>
      </article>
    </div>

    <form class="composer" @submit.prevent="sendMessage">
      <textarea v-model="draft" rows="3" placeholder="Ask Jarvis..." />
      <VoiceButton :disabled="loading" @transcribed="sendVoiceText" @error="showVoiceError" />
      <button :disabled="loading || !draft.trim()" type="submit">
        {{ loading ? 'Sending' : 'Send' }}
      </button>
    </form>
  </section>
</template>

<script setup>
import { ref } from 'vue'
import VoiceButton from './VoiceButton.vue'

const props = defineProps({
  provider: {
    type: String,
    required: true,
  },
})

const draft = ref('')
const loading = ref(false)
const conversationId = ref(null)
const messages = ref([
  {
    id: crypto.randomUUID(),
    role: 'assistant',
    content: 'Jarvis is ready. Ollama is selected by default.',
  },
])

async function sendMessage() {
  const content = draft.value.trim()
  if (!content) return
  await sendText(content)
}

async function sendVoiceText(text) {
  const content = text.trim()
  if (!content) return
  draft.value = ''
  await sendText(content)
}

function showVoiceError(message) {
  messages.value.push({ id: crypto.randomUUID(), role: 'assistant', content: message })
}

async function sendText(content) {
  messages.value.push({ id: crypto.randomUUID(), role: 'user', content })
  draft.value = ''
  loading.value = true

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        message: content,
        provider: props.provider,
        conversation_id: conversationId.value,
      }),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Chat request failed')
    conversationId.value = data.conversation_id
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'assistant',
      content: data.message || '(empty response)',
      external: data.metadata?.external_provider_used,
      provider: data.metadata?.provider,
    })
  } catch (error) {
    messages.value.push({ id: crypto.randomUUID(), role: 'assistant', content: error.message })
  } finally {
    loading.value = false
  }
}
</script>
