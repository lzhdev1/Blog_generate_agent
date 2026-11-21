<template>
  <section class="account-sheet" :aria-label="title">
    <div class="account-intro">
      <div><h1>{{ title }}</h1><p>{{ description }}</p></div>
      <img src="@/assets/press.webp" alt="" width="1275" height="850" />
    </div>
    <div class="account-fields"><slot /><div class="account-switch"><slot name="footer" /></div></div>
  </section>
</template>

<script setup>
defineProps({ title: String, description: String })
</script>

<style src="@/assets/styles/account.css"></style>
