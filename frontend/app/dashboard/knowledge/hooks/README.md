# Knowledge page hooks — M40.1 拆分说明

> `frontend/app/dashboard/knowledge/page.tsx` 2026-10-05 从 **2098 行** god component
> 拆成 **1000 行(-52.3%)** hook 编排层。本目录是 5 个 hook 的契约总览,**page.tsx 是单一调用入口**,
> 新 feature 直接加在对应 hook / `components/knowledge/`,不再 push 到 god component。

## 1. 6 hooks 总览

| Hook | LOC | 职责 | 关键 state |
|---|---|---|---|
| `useKnowledgeList` | 390 | KB 列表 + CRUD + blocker modal + drag-drop KB | `data / loading / page / selectedKB / editingKB / blockerModal / form / editForm / searchWeights / editSearchWeights` + KB CRUD |
| `useWorkspaceTree` | 424 | workspace → KB → folder 三层 sidebar + 4 modal + 8 handler | `selectedWorkspaceId / selectedFolderId / currentUserId` + 4 useQuery + 4 modal open flag |
| `useDocumentUpload` | 105 | 上传文件 mutation + doc type picker | `selectedDocType` + `uploadMutation` |
| `useDocumentList` | 439 | 文档列表 + 重试/删除/分块/重新分块 + WS 通知订阅 | `documents / loadingDocs / docList* / chunks* / rechunk* / retryingDocId / deletingDocId` |
| `useDocumentSearch` | 178 | 文档搜索 + 高级选项 + detail modal | `searchQuery / searchOptions / searchResults / searching / selectedDoc / detailModalVisible` |

> 命名约定:`kb` = useKnowledgeList, `ws` = useWorkspaceTree, `up` = useDocumentUpload,
> `c1` = useDocumentList, `s2` = useDocumentSearch。

## 2. 5 子组件 总览

| 组件 | LOC | 替换 | 文件 |
|---|---|---|---|
| `<CreateKBModal>` | 188 | page.tsx 790-875 (M28 创建 KB) | `frontend/components/knowledge/CreateKBModal.tsx` |
| `<EditKBModal>` | 188 | page.tsx 877-957 (M28 编辑 KB) | `frontend/components/knowledge/EditKBModal.tsx` |
| `<BlockerModal>` | 91 | page.tsx 1215-1282 (M28 422 拦截) | `frontend/components/knowledge/BlockerModal.tsx` |
| `<SearchCard>` | 226 | page.tsx 643-753 (搜索 Card + 高级选项 + 结果列表) | `frontend/components/knowledge/SearchCard.tsx` |
| `<ViewChunksModal>` | 127 | page.tsx 1059-1138 (分块详情 + 末 8 位 vector_id) | `frontend/components/knowledge/ViewChunksModal.tsx` |

> 保留 inline(< 80 LOC 或耦合过紧):Documents List wrapper、Doc List Modal wrapper、Detail Modal(30 行)、Re-chunk Modal(73 行)、Breadcrumb、KB Detail Card、`DeleteDocumentAction` helper。

## 3. page.tsx 调用顺序(关键!)

```tsx
const kb = useKnowledgeList({                          // Phase 2
  selectedWorkspaceId: wsRef.current,                  // ← 关键:从 wsRef 读
  onKbSelectFetchDocs: c1.refreshDocuments,
  onKbChangeCleanup: (kb) => { /* 清 search + 清 folder */ },
  loadedEmbeddingModels: kb.loadedEmbeddingModels,
});
const ws = useWorkspaceTree({ selectedKB: kb.selectedKB, onKbChange: kb.setSelectedKB });
const up = useDocumentUpload({
  currentFolderId: ws.selectedFolderId,
  onUploadSuccess: async (kbId) => { await kb.refreshKbList(); await c1.refreshDocuments(kbId); },
});
const c1 = useDocumentList({
  selectedKB: kb.selectedKB,
  selectedFolderId: ws.selectedFolderId,
  refreshKbList: kb.refreshKbList,
  allKBs: kb.data,
});
const s2 = useDocumentSearch({ selectedKB: kb.selectedKB });
```

### 3.1 为什么 `kb` 在 `ws` 之前?

`kb.data` 依赖 `selectedWorkspaceId` 过滤,而 `selectedWorkspaceId` 来自 `ws`。如果 `ws` 在 `kb` 之前 init,
`kb` 拿到的 `args.selectedWorkspaceId` 是 hook **init 时刻**的值(可能是 null / 旧值)。

**TDZ 解法 —— `useRef` 同步桥**:

```tsx
const wsRef = useRef<number | null>(null);
wsRef.current = ws.selectedWorkspaceId;   // 每次 render 同步给 kb
```

`useKnowledgeList` 内部 handler 读 `wsIdRef.current`,**不依赖 args closure capture**,
拿到的是当前 render 时刻的最新值。

## 4. 跨 hook 通信矩阵

| Hook | 读 | 调 |
|---|---|---|
| `useKnowledgeList` (kb) | `ws.selectedWorkspaceId`(via wsRef) | `c1.refreshDocuments` / `kb.setSelectedKB` |
| `useWorkspaceTree` (ws) | `kb.selectedKB` | `kb.setSelectedKB` / `kb.setSelectedWorkspaceId` / `kb.setSelectedFolderId` / `c1.clearDocuments` |
| `useDocumentUpload` (up) | `kb.selectedKB`, `ws.selectedFolderId` | `kb.refreshKbList`, `c1.refreshDocuments` |
| `useDocumentList` (c1) | `kb.selectedKB`, `ws.selectedFolderId`, `kb.data`(allKBs), `kb.refreshKbList` | — |
| `useDocumentSearch` (s2) | `kb.selectedKB` | — |

**原则:props-down + callbacks-up,不上 Context。**

Context 在每个 state 变化时 re-render 所有 hook consumer,5 个 hook × ~30 state slot 会让
`React.memo` 失效。lift 到 page.tsx ~10 行/hook 但可调试,跟 chat refactor 模式一致。

## 5. 加新 feature 时怎么 hook 化

### 5.1 加新 modal(参考 `<CreateKBModal>`)

1. 在 `frontend/components/knowledge/XxxModal.tsx` 写纯 JSX 渲染层,state 通过 props 传入。
2. modal 涉及的 state / handler 放到对应 hook(看上面矩阵),hook 暴露 setter + open flag。
3. page.tsx 加 `<XxxModal ... />` 一行 JSX。
4. 测试不需要改 — mock 不变,测试只断言 modal 出现 + 按钮触发回调。

### 5.2 加新文档状态(参考 Reading 列)

新 state 涉及多 hook 协调 → 决定归属:

| 场景 | 归属 |
|---|---|
| 只在 documents list 用 | `c1`(useDocumentList) |
| 只 KB list 影响 | `kb`(useKnowledgeList) |
| 跨 KB + workspace 联动 | `ws`(useWorkspaceTree) |
| 跨 KB + documents + upload | 抽 **新 hook**,page 层 inline 编排 |

### 5.3 加新 WS notification 处理

直接在 `useDocumentList` 的 `useEffect` 里加 — 已订阅 `useNotificationsStore`。
新事件类型加 if 分支,不需要新 hook。

## 6. 关键约束(踩过的坑)

1. **`setter prop 类型对齐`** —— hook 暴露 `(v: T) => void` setter,子组件 prop 也用
   `(v: T) => void`,**不要** `Dispatch<SetStateAction<T>>`(后者支持 prev callback,
   hook 不需要这复杂度)。
2. **`useRef` 跨 hook TDZ 同步** —— hook 间 init 顺序固定时用 wsRef.current = ws.xxx
   同步;handler 内部读 ref.current,不依赖 args closure。
3. **bridge useEffect 内部** —— selectedKB / selectedFolderId 变化 → 自动 fetchDocuments /
   fetchChunks,**免暴露 fetchXxx 接口给 page 层**。
4. **`useCallback deps=[]` + ref 读取** —— handler init 用 empty deps,内部读
   `kbIdRef.current / folderIdRef.current`,避免 callback 重建污染其他 hook。
5. **`Workspace` type mismatch** —— `owner_id` 实际是 `number | null | undefined`,
   必须 import `Workspace` 用 `Workspace[]`,不要用 `any[]`。
6. **modal form 重置** —— open create → cancel → reopen,确认无 stale 值。
   `editForm.resetFields()` 在 cancel 时显式调用。

## 7. 测试基线

| 套件 | 结果 |
|------|------|
| `__tests__/knowledge/page-workspace-integration.test.tsx` (7) | ✓ |
| `__tests__/knowledge/page-faq-tab.test.tsx` (6) | ✓ |
| `__tests__/knowledge/page-drag-drop-integration.test.tsx` | ✓ |
| `__tests__/knowledge/delete-blockers.test.tsx` | ✓ |
| `__tests__/knowledge/page-rbac-integration.test.tsx` | ✓ |
| `__tests__/knowledge/faq-tab.test.tsx` | ✓ |

**6 文件 / 34 测试全过**,`tsc --noEmit` 0 新错误(knowledge 范围)。

## 8. 与 chat refactor 一致性(2026-06-16 commit `0ce9ab1`)

- hooks 目录结构:`app/dashboard/<feature>/hooks/` ✓
- 组件目录:`components/<feature>/` ✓
- 单 hook LOC 上限:< 400 LOC(useDocumentList 439 行稍微超,继续分时优先拆它)
- 跨 hook 通信:props-down + callback-up,不上 Context ✓
- 测试策略:依赖现有 6 个 vitest 文件,mock 不变 ✓
- commit message:`refactor(knowledge):` 中文 ✓
- CLAUDE.md §9:标识符英文硬性,docstring 英文 1 行 + 中文详细,行内 # 中文 ✓

## 9. 相关

- Memory:`~/.claude/projects/.../memory/m40-1-knowledge-refactor.md`
- Plan:`C:\Users\wma19\.claude\plans\wobbly-popping-lovelace.md`
- 父任务 plan:`m40-p0-security-ci` / `m40-1-quick-wins`(同次 M40/M40.1 包)