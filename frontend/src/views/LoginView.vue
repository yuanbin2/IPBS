<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Lock, UserFilled } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { useAuthStore } from "../stores/auth";

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();
const mode = ref<"login" | "register">("login");
const username = ref("");
const password = ref("");
const workspaceKey = ref("default");
const role = ref("admin");
const loading = ref(false);

async function submit() {
  loading.value = true;
  try {
    if (mode.value === "login") {
      await auth.login(username.value, password.value);
      ElMessage.success("登录成功");
    } else {
      await auth.register(username.value, password.value, role.value, workspaceKey.value);
      ElMessage.success("注册成功");
    }
    router.replace(typeof route.query.redirect === "string" ? route.query.redirect : "/");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "认证失败");
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-panel">
      <header>
        <div class="auth-logo">
          <el-icon><Lock /></el-icon>
        </div>
        <p class="eyebrow">Knowledge Agent</p>
        <h1>{{ mode === "login" ? "登录工作台" : "注册管理员账号" }}</h1>
      </header>

      <el-radio-group v-model="mode" class="auth-tabs">
        <el-radio-button label="login">登录</el-radio-button>
        <el-radio-button label="register">注册</el-radio-button>
      </el-radio-group>

      <form class="auth-form" @submit.prevent="submit">
        <el-input v-model="username" placeholder="用户名" :prefix-icon="UserFilled" />
        <el-input v-model="password" placeholder="密码，至少 8 位" type="password" show-password :prefix-icon="Lock" />
        <template v-if="mode === 'register'">
          <el-input v-model="workspaceKey" placeholder="Workspace" />
          <el-select v-model="role">
            <el-option label="管理员" value="admin" />
            <el-option label="操作员" value="operator" />
            <el-option label="访客" value="visitor" />
          </el-select>
        </template>
        <el-button type="primary" native-type="submit" :loading="loading">
          {{ mode === "login" ? "登录" : "注册并进入" }}
        </el-button>
      </form>
    </section>
  </main>
</template>
