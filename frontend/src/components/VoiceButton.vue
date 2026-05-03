<template>
  <button class="voice-button" :disabled="disabled || transcribing" type="button" @click="toggleRecording">
    {{ label }}
  </button>
</template>

<script setup>
import { computed, ref } from 'vue'

defineProps({
  disabled: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['transcribed', 'error'])
const mediaRecorder = ref(null)
const chunks = ref([])
const recording = ref(false)
const transcribing = ref(false)

const label = computed(() => {
  if (transcribing.value) return 'Transcribing'
  return recording.value ? 'Stop' : 'Voice'
})

async function toggleRecording() {
  if (recording.value) {
    mediaRecorder.value?.stop()
    return
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    chunks.value = []
    mediaRecorder.value = new MediaRecorder(stream)
    mediaRecorder.value.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.value.push(event.data)
    }
    mediaRecorder.value.onstop = async () => {
      stream.getTracks().forEach((track) => track.stop())
      recording.value = false
      await transcribe()
    }
    mediaRecorder.value.start()
    recording.value = true
  } catch (error) {
    emit('error', error.message || 'Microphone unavailable')
  }
}

async function transcribe() {
  if (!chunks.value.length) return
  transcribing.value = true
  const blob = new Blob(chunks.value, { type: 'audio/webm' })
  const formData = new FormData()
  formData.append('file', blob, 'voice.webm')

  try {
    const response = await fetch('/api/voice/transcribe', {
      method: 'POST',
      credentials: 'include',
      body: formData,
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Transcription failed')
    emit('transcribed', data.text)
  } catch (error) {
    emit('error', error.message || 'Transcription failed')
  } finally {
    transcribing.value = false
  }
}
</script>
