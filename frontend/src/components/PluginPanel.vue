<template>
  <section class="panel">
    <header>
      <h2>Plugins</h2>
      <button @click="loadPlugins">Refresh</button>
    </header>

    <ul>
      <li v-for="plugin in plugins" :key="plugin.tool_name">
        <button class="link-button" @click="selectPlugin(plugin.tool_name)">
          <span>{{ plugin.tool_name }}</span>
          <small>{{ plugin.permissions }} · {{ plugin.enabled ? 'enabled' : 'disabled' }}</small>
        </button>
      </li>
    </ul>

    <article v-if="selected" class="memory-detail">
      <h3>{{ selected.tool_name }}</h3>
      <small>{{ selected.version }} · {{ selected.permissions }}</small>
      <p>{{ selected.description }}</p>
      <form class="memory-form" @submit.prevent="runSelected">
        <input v-model="runText" placeholder="text" />
        <button :disabled="!selected.enabled">Run</button>
      </form>
      <pre v-if="runResult">{{ runResult }}</pre>
    </article>

    <article class="memory-detail">
      <h3>Install</h3>
      <input type="file" accept=".zip" @change="selectPackage" />
      <button :disabled="!packageBase64" @click="previewInstall">Preview</button>

      <div v-if="installPreview">
        <small>{{ installPreview.risk_level }} · {{ installPreview.permissions_requested }}</small>
        <p v-if="installPreview.forbidden.length">{{ installPreview.forbidden.join('; ') }}</p>
        <p>Add: {{ installPreview.files_to_add.length }} · Modify: {{ installPreview.files_to_modify.length }}</p>
        <textarea v-model="approvalText" rows="3" placeholder="Approval phrases, if required" />
        <input v-model="adminPassword" type="password" placeholder="Admin password, if required" />
        <button @click="applyInstall">Apply</button>
      </div>
      <pre v-if="installMessage">{{ installMessage }}</pre>
    </article>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'

const plugins = ref([])
const selected = ref(null)
const runText = ref('')
const runResult = ref('')
const packageName = ref('')
const packageBase64 = ref('')
const installPreview = ref(null)
const installMessage = ref('')
const approvalText = ref('')
const adminPassword = ref('')

async function loadPlugins() {
  const response = await fetch('/api/plugins', { credentials: 'include' })
  if (response.ok) {
    plugins.value = (await response.json()).plugins
  }
}

async function selectPlugin(name) {
  const response = await fetch(`/api/plugins/${encodeURIComponent(name)}`, { credentials: 'include' })
  if (response.ok) {
    selected.value = await response.json()
    runResult.value = ''
  }
}

async function runSelected() {
  if (!selected.value) return
  const response = await fetch(`/api/plugins/${encodeURIComponent(selected.value.tool_name)}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ args: { text: runText.value }, confirmed: true }),
  })
  runResult.value = JSON.stringify(await response.json(), null, 2)
}

function selectPackage(event) {
  const file = event.target.files?.[0]
  if (!file) return
  packageName.value = file.name
  const reader = new FileReader()
  reader.onload = () => {
    const result = String(reader.result || '')
    packageBase64.value = result.includes(',') ? result.split(',')[1] : result
  }
  reader.readAsDataURL(file)
}

async function previewInstall() {
  installMessage.value = ''
  const response = await fetch('/api/plugins/install/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ filename: packageName.value, package_base64: packageBase64.value }),
  })
  const data = await response.json()
  if (response.ok) {
    installPreview.value = data
  } else {
    installMessage.value = data.detail || 'Preview failed'
  }
}

async function applyInstall() {
  const response = await fetch('/api/plugins/install/apply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({
      filename: packageName.value,
      package_base64: packageBase64.value,
      admin_password: adminPassword.value || null,
      approval_text: approvalText.value,
    }),
  })
  const data = await response.json()
  installMessage.value = JSON.stringify(data, null, 2)
  if (response.ok) {
    installPreview.value = null
    await loadPlugins()
  }
}

onMounted(loadPlugins)
</script>
