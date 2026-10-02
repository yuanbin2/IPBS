import { createApp } from "vue";
import { createPinia } from "pinia";
import {
  ElAlert,
  ElButton,
  ElCollapse,
  ElCollapseItem,
  ElCheckbox,
  ElDialog,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElOption,
  ElProgress,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElSwitch,
  ElTag
} from "element-plus";
import "element-plus/es/components/alert/style/css";
import "element-plus/es/components/button/style/css";
import "element-plus/es/components/collapse/style/css";
import "element-plus/es/components/checkbox/style/css";
import "element-plus/es/components/dialog/style/css";
import "element-plus/es/components/drawer/style/css";
import "element-plus/es/components/dropdown/style/css";
import "element-plus/es/components/form/style/css";
import "element-plus/es/components/icon/style/css";
import "element-plus/es/components/input/style/css";
import "element-plus/es/components/message/style/css";
import "element-plus/es/components/message-box/style/css";
import "element-plus/es/components/progress/style/css";
import "element-plus/es/components/radio/style/css";
import "element-plus/es/components/select/style/css";
import "element-plus/es/components/switch/style/css";
import "element-plus/es/components/tag/style/css";

import App from "./App.vue";
import router from "./router";
import { installApiClient } from "./api/client";
import "./style.css";

installApiClient();

const app = createApp(App).use(createPinia()).use(router);
[
  ElAlert,
  ElButton,
  ElCollapse,
  ElCollapseItem,
  ElCheckbox,
  ElDialog,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElOption,
  ElProgress,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElSwitch,
  ElTag
].forEach((component) => app.use(component));
app.mount("#app");
