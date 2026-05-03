<template>
  <main class="app-shell">
    <section class="workspace">
      <header class="topbar">
        <div>
          <h1>Jarvis</h1>
          <p>Local-first assistant</p>
        </div>
        <LoginPanel />
        <ProviderSelector v-model="provider" />
      </header>

      <ChatBox :provider="provider" />
    </section>

    <aside class="side-panel">
      <MemoryPanel />
      <PluginPanel />
    </aside>
  </main>
</template>

<script setup>
import { ref } from 'vue'
import ChatBox from '../components/ChatBox.vue'
import LoginPanel from '../components/LoginPanel.vue'
import MemoryPanel from '../components/MemoryPanel.vue'
import PluginPanel from '../components/PluginPanel.vue'
import ProviderSelector from '../components/ProviderSelector.vue'

const provider = ref('local')
</script>
