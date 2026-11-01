import { createApp } from "vue";
import { createPinia } from "pinia";
import {
  ElAlert,
  ElButton,
  ElCollapse,
  ElCollapseItem,
  ElCheckbox,
  ElDialog,
  ElDivider,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
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
import "element-plus/es/components/divider/style/css";
import "element-plus/es/components/drawer/style/css";
import "element-plus/es/components/dropdown/style/css";
import "element-plus/es/components/empty/style/css";
import "element-plus/es/components/form/style/css";
import "element-plus/es/components/icon/style/css";
import "element-plus/es/components/input/style/css";
import "element-plus/es/components/message/style/css";
import "element-plus/es/components/message-box/style/css";
import "element-plus/es/components/progress/style/css";
import "element-plus/es/components/radio/style/css";
// el-radio-button 的样式（隐藏原生 input、pill 内衬）在独立文件里，
// 缺了它原生 radio 会裸露成一排圆点（2026-10 全站 UX 巡检发现）。
import "element-plus/es/components/radio-button/style/css";
import "element-plus/es/components/select/style/css";
import "element-plus/es/components/switch/style/css";
import "element-plus/es/components/tag/style/css";

import App from "./App.vue";
import router from "./router";
import { installApiClient } from "./api/client";
import { configureMarkdownExtensions } from "./features/blog/utils/markdownExtensions";
import "./style.css";

installApiClient();
// 公式/流程图渲染资源指向本站同源副本，不请求第三方 CDN（详见 markdownExtensions.ts）。
configureMarkdownExtensions();

const app = createApp(App).use(createPinia()).use(router);
[
  ElAlert,
  ElButton,
  ElCollapse,
  ElCollapseItem,
  ElCheckbox,
  ElDialog,
  ElDivider,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
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
// radio 系列在部分 dev 环境下 use() 注册会静默丢失（运行时注册表缺 ElRadioGroup，
// 页面控制台报 Failed to resolve component: el-radio-group），显式补注册一次（幂等）。
app.component("ElRadioGroup", ElRadioGroup);
app.component("ElRadioButton", ElRadioButton);
app.mount("#app");
