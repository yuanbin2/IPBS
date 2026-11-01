/**
 * VditorEditor 的 v-model 外部同步判定。
 *
 * 背景：vditor 的 WYSIWYG 在某些输入（典型：空段落里敲回车）后，
 * `input` 回调吐出的 Markdown 与随后 `getValue()` 序列化结果不完全一致
 * （往返抖动）。若此刻机械地执行「值不同就 setValue()」，setValue 会重建
 * 整个可编辑 DOM，把光标丢回文档开头——正是用户看到的「敲回车跳到文章最前」。
 *
 * 策略：值相同不动作；编辑器持有焦点（用户正在输入或 IME 组词中）时一律不回写，
 * 待焦点离开编辑器（focusout 到外部）时再补一次同步。
 */

/** 编辑器 DOM（.vditor 根元素）内是否持有焦点；实例未就绪视为未聚焦。 */
export function isEditorFocused(root: Element | null | undefined): boolean {
  if (!root) return false;
  return root.contains(document.activeElement);
}

/**
 * 是否应当把外部值写回编辑器。
 * - 值相同：不写（写也是重排）。
 * - 编辑器聚焦：不写，避免打断输入与光标（往返抖动就发生在输入瞬间）。
 */
export function shouldSyncExternalValue(
  incoming: string,
  current: string,
  focused: boolean,
): boolean {
  if (incoming === current) return false;
  return !focused;
}
