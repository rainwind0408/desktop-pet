<template>
  <div id="app">
    <nav class="nav-bar">
      <router-link to="/" class="nav-link">主页</router-link>
      <router-link to="/settings" class="nav-link">设置</router-link>
    </nav>
    <router-view />
  </div>
</template>

<script>
export default {
  name: 'App'
}
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

#app {
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.nav-bar {
  display: flex;
  gap: 4px;
  padding: 6px 16px;
  background: rgba(0, 0, 0, 0.3);
  z-index: 10;
}

.nav-link {
  color: rgba(255, 255, 255, 0.7);
  text-decoration: none;
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 13px;
  transition: all 0.2s;
}

.nav-link:hover {
  background: rgba(255, 255, 255, 0.15);
  color: white;
}

.nav-link.router-link-exact-active {
  background: rgba(255, 255, 255, 0.2);
  color: white;
}
</style>
