<template>
  <section class="panel">
    <header>
      <h2>Memory</h2>
      <button @click="loadMemories">Refresh</button>
    </header>

    <form class="memory-form" @submit.prevent="saveFact">
      <select v-model="memoryType" aria-label="Memory type">
        <option value="fact">fact</option>
        <option value="project">project</option>
        <option value="task">task</option>
        <option value="script">script</option>
        <option value="log">log</option>
        <option value="search_result">search_result</option>
        <option value="conversation_summary">conversation_summary</option>
        <option value="system_change">system_change</option>
      </select>
      <input v-model="title" placeholder="Title" />
      <input v-model="content" placeholder="Content" />
      <button :disabled="!title.trim() || !content.trim()">Add</button>
    </form>

    <form class="memory-form" @submit.prevent="searchMemories">
      <input v-model="query" placeholder="Search memory" />
      <button :disabled="!query.trim()">Search</button>
    </form>

    <ul>
      <li v-for="item in memories" :key="item.id">
        <button class="link-button" @click="selectMemory(item.id)">
          <span>{{ item.title }}</span>
          <small>{{ item.memory_type }}</small>
        </button>
      </li>
    </ul>

    <article v-if="selected" class="memory-detail">
      <h3>{{ selected.title }}</h3>
      <small>{{ selected.memory_type }} · {{ selected.source }}</small>
      <p>{{ selected.content }}</p>
      <p v-if="selected.tags.length" class="tags">{{ selected.tags.join(', ') }}</p>
    </article>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'

const memoryType = ref('fact')
const title = ref('')
const content = ref('')
const query = ref('')
const memories = ref([])
const selected = ref(null)

async function loadMemories() {
  const response = await fetch('/api/memory', { credentials: 'include' })
  if (response.ok) {
    memories.value = (await response.json()).memories
  }
}

async function saveFact() {
  const payload = {
    memory_type: memoryType.value,
    title: title.value.trim(),
    content: content.value.trim(),
  }
  if (!payload.title || !payload.content) return
  const response = await fetch('/api/memory', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload),
  })
  if (response.ok) {
    title.value = ''
    content.value = ''
    await loadMemories()
  }
}

async function searchMemories() {
  const term = query.value.trim()
  if (!term) return loadMemories()
  const response = await fetch(`/api/memory/search?q=${encodeURIComponent(term)}`, { credentials: 'include' })
  if (response.ok) {
    memories.value = (await response.json()).memories
  }
}

async function selectMemory(id) {
  const response = await fetch(`/api/memory/${id}`, { credentials: 'include' })
  if (response.ok) {
    selected.value = await response.json()
  }
}

onMounted(loadMemories)
</script>
