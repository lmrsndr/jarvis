<template>
  <section class="login-panel">
    <span>{{ authenticated ? 'Session active' : 'Remote login' }}</span>
    <form v-if="!authenticated" @submit.prevent="login">
      <input v-model="password" type="password" placeholder="Admin password" />
      <button :disabled="!password">Login</button>
    </form>
    <button v-else @click="logout">Logout</button>
    <small v-if="message">{{ message }}</small>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'

const authenticated = ref(false)
const password = ref('')
const message = ref('')

async function loadSession() {
  const response = await fetch('/api/system/session', { credentials: 'include' })
  if (response.ok) {
    authenticated.value = (await response.json()).authenticated
  }
}

async function login() {
  message.value = ''
  const response = await fetch('/api/system/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ password: password.value }),
  })
  if (response.ok) {
    authenticated.value = true
    password.value = ''
  } else {
    message.value = (await response.json()).detail || 'Login failed'
  }
}

async function logout() {
  await fetch('/api/system/logout', { method: 'POST', credentials: 'include' })
  authenticated.value = false
}

onMounted(loadSession)
</script>
