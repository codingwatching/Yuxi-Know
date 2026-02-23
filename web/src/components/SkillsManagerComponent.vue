<template>
  <div class="skills-manager">
    <div class="header-section">
      <div class="header-content">
        <h3 class="title">Skills 管理</h3>
        <p class="description">导入、编辑、导出和删除技能包。技能内容保存在文件系统，元数据保存在数据库。</p>
      </div>
      <div class="header-actions">
        <a-upload
          accept=".zip"
          :show-upload-list="false"
          :custom-request="handleImportUpload"
          :disabled="loading || importing"
        >
          <a-button type="primary" :loading="importing">导入 ZIP</a-button>
        </a-upload>
        <a-button @click="fetchSkills" :disabled="loading">刷新</a-button>
      </div>
    </div>

    <a-spin :spinning="loading">
      <div class="content-layout">
        <div class="skills-list-panel">
          <a-table
            size="small"
            :columns="columns"
            :data-source="skills"
            :pagination="false"
            row-key="slug"
            :custom-row="bindSkillRow"
            :row-class-name="rowClassName"
            :scroll="{ y: 360 }"
          />
        </div>

        <div class="skill-detail-panel">
          <a-empty v-if="!currentSkill" description="请选择一个 Skill" />

          <template v-else>
            <div class="detail-header">
              <div class="detail-title">
                <strong>{{ currentSkill.name }}</strong>
                <span class="slug">({{ currentSkill.slug }})</span>
                <span class="dependency-summary">
                  工具 {{ (currentSkill.tool_dependencies || []).length }} · MCP
                  {{ (currentSkill.mcp_dependencies || []).length }} · Skills
                  {{ (currentSkill.skill_dependencies || []).length }}
                </span>
              </div>
              <div class="detail-actions">
                <a-button size="small" @click="reloadTree">刷新目录</a-button>
                <a-button size="small" @click="openCreateModal(false)">新建文件</a-button>
                <a-button size="small" @click="openCreateModal(true)">新建目录</a-button>
                <a-button size="small" @click="handleExport">导出 ZIP</a-button>
                <a-button danger size="small" @click="confirmDeleteSkill">删除 Skill</a-button>
              </div>
            </div>

            <div class="dependency-panel">
              <div class="dependency-header">
                <span class="dependency-title">依赖管理</span>
                <a-button
                  type="primary"
                  size="small"
                  :loading="savingDependencies"
                  :disabled="loading || savingDependencies"
                  @click="saveDependencies"
                >
                  保存依赖
                </a-button>
              </div>
              <a-form layout="vertical" class="dependency-form">
                <a-form-item label="工具依赖">
                  <a-select
                    v-model:value="dependencyForm.tool_dependencies"
                    mode="multiple"
                    :options="toolDependencyOptions"
                    placeholder="选择工具依赖"
                    :disabled="loading || savingDependencies"
                    allow-clear
                  />
                </a-form-item>
                <a-form-item label="MCP 依赖">
                  <a-select
                    v-model:value="dependencyForm.mcp_dependencies"
                    mode="multiple"
                    :options="mcpDependencyOptions"
                    placeholder="选择 MCP 服务依赖"
                    :disabled="loading || savingDependencies"
                    allow-clear
                  />
                </a-form-item>
                <a-form-item label="Skill 依赖">
                  <a-select
                    v-model:value="dependencyForm.skill_dependencies"
                    mode="multiple"
                    :options="skillDependencyOptions"
                    placeholder="选择 Skill 依赖"
                    :disabled="loading || savingDependencies"
                    allow-clear
                  />
                </a-form-item>
              </a-form>
            </div>

            <div class="detail-body">
              <div class="tree-panel">
                <div class="tree-toolbar">
                  <span class="tree-title">目录树</span>
                  <a-button
                    size="small"
                    danger
                    @click="confirmDeleteNode"
                    :disabled="!selectedPath || selectedPath === 'SKILL.md'"
                  >
                    删除节点
                  </a-button>
                </div>
                <a-tree
                  :tree-data="treeData"
                  :selected-keys="selectedTreeKeys"
                  :default-expand-all="true"
                  @select="handleTreeSelect"
                />
              </div>

              <div class="editor-panel">
                <div class="editor-toolbar">
                  <span class="editor-path">{{ selectedPath || '请选择文本文件' }}</span>
                  <a-button
                    type="primary"
                    size="small"
                    @click="saveCurrentFile"
                    :disabled="!canSave"
                    :loading="savingFile"
                  >
                    保存
                  </a-button>
                </div>

                <a-empty v-if="!selectedPath || selectedIsDir" description="请选择文本文件后编辑" />
                <a-textarea
                  v-else
                  v-model:value="fileContent"
                  :rows="22"
                  class="file-editor"
                  placeholder="文件内容"
                />
              </div>
            </div>
          </template>
        </div>
      </div>
    </a-spin>

    <a-modal
      v-model:open="createModalVisible"
      :title="createForm.isDir ? '新建目录' : '新建文件'"
      @ok="handleCreateNode"
      :confirm-loading="creatingNode"
      :maskClosable="false"
    >
      <a-form layout="vertical">
        <a-form-item label="路径（相对 skill 根目录）" required>
          <a-input v-model:value="createForm.path" placeholder="例如 prompts/guide.md" />
        </a-form-item>
        <a-form-item v-if="!createForm.isDir" label="文件内容">
          <a-textarea v-model:value="createForm.content" :rows="8" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { skillApi } from '@/apis/skill_api'

const loading = ref(false)
const importing = ref(false)
const savingFile = ref(false)
const creatingNode = ref(false)
const savingDependencies = ref(false)

const skills = ref([])
const currentSkill = ref(null)
const treeData = ref([])
const selectedTreeKeys = ref([])
const selectedPath = ref('')
const selectedIsDir = ref(false)
const fileContent = ref('')
const originalFileContent = ref('')

const createModalVisible = ref(false)
const createForm = reactive({
  path: '',
  isDir: false,
  content: ''
})
const dependencyOptions = reactive({
  tools: [],
  mcps: [],
  skills: []
})
const dependencyForm = reactive({
  tool_dependencies: [],
  mcp_dependencies: [],
  skill_dependencies: []
})

const columns = [
  { title: '名称', dataIndex: 'name', key: 'name', width: 180, ellipsis: true },
  { title: 'Slug', dataIndex: 'slug', key: 'slug', width: 180, ellipsis: true },
  {
    title: '依赖',
    key: 'dependencies',
    width: 150,
    customRender: ({ record }) =>
      `T${(record.tool_dependencies || []).length} / M${(record.mcp_dependencies || []).length} / S${(record.skill_dependencies || []).length}`
  },
  { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
  { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 180, ellipsis: true }
]

const canSave = computed(() => {
  if (!selectedPath.value || selectedIsDir.value) return false
  return fileContent.value !== originalFileContent.value
})

const rowClassName = (record) => {
  return currentSkill.value?.slug === record.slug ? 'selected-row' : ''
}

const toolDependencyOptions = computed(() =>
  (dependencyOptions.tools || []).map((item) => ({ label: item, value: item }))
)

const mcpDependencyOptions = computed(() =>
  (dependencyOptions.mcps || []).map((item) => ({ label: item, value: item }))
)

const skillDependencyOptions = computed(() =>
  (dependencyOptions.skills || [])
    .filter((slug) => slug !== currentSkill.value?.slug)
    .map((item) => ({ label: item, value: item }))
)

const bindSkillRow = (record) => ({
  onClick: () => selectSkill(record)
})

const normalizeTree = (nodes) => {
  return (nodes || []).map((node) => ({
    title: node.name,
    key: node.path,
    isLeaf: !node.is_dir,
    path: node.path,
    is_dir: node.is_dir,
    children: node.is_dir ? normalizeTree(node.children || []) : undefined
  }))
}

const resetFileState = () => {
  selectedPath.value = ''
  selectedIsDir.value = false
  selectedTreeKeys.value = []
  fileContent.value = ''
  originalFileContent.value = ''
}

const fetchSkills = async () => {
  loading.value = true
  try {
    const result = await skillApi.listSkills()
    skills.value = result?.data || []

    if (currentSkill.value) {
      const latest = skills.value.find((item) => item.slug === currentSkill.value.slug)
      if (!latest) {
        currentSkill.value = null
        treeData.value = []
        resetFileState()
      } else {
        currentSkill.value = latest
        syncDependencyFormFromSkill(latest)
      }
    }
    await fetchDependencyOptions()
  } catch (error) {
    message.error(error.message || '获取 Skills 列表失败')
  } finally {
    loading.value = false
  }
}

const fetchDependencyOptions = async () => {
  try {
    const result = await skillApi.getSkillDependencyOptions()
    const data = result?.data || {}
    dependencyOptions.tools = data.tools || []
    dependencyOptions.mcps = data.mcps || []
    dependencyOptions.skills = data.skills || []
  } catch (error) {
    message.error(error.message || '获取依赖选项失败')
  }
}

const syncDependencyFormFromSkill = (skillRecord) => {
  dependencyForm.tool_dependencies = [...(skillRecord?.tool_dependencies || [])]
  dependencyForm.mcp_dependencies = [...(skillRecord?.mcp_dependencies || [])]
  dependencyForm.skill_dependencies = [...(skillRecord?.skill_dependencies || [])]
}

const reloadTree = async () => {
  if (!currentSkill.value) return
  loading.value = true
  try {
    const result = await skillApi.getSkillTree(currentSkill.value.slug)
    treeData.value = normalizeTree(result?.data || [])
  } catch (error) {
    message.error(error.message || '加载目录树失败')
  } finally {
    loading.value = false
  }
}

const selectSkill = async (record) => {
  currentSkill.value = record
  syncDependencyFormFromSkill(record)
  resetFileState()
  await reloadTree()
}

const handleTreeSelect = async (keys, info) => {
  if (!keys?.length) {
    resetFileState()
    return
  }

  const node = info?.node || {}
  const path = node.path || node.key
  const isDir = !!node.is_dir
  selectedTreeKeys.value = [path]
  selectedPath.value = path
  selectedIsDir.value = isDir

  if (isDir) {
    fileContent.value = ''
    originalFileContent.value = ''
    return
  }

  try {
    const result = await skillApi.getSkillFile(currentSkill.value.slug, path)
    const content = result?.data?.content || ''
    fileContent.value = content
    originalFileContent.value = content
  } catch (error) {
    message.error(error.message || '读取文件失败')
  }
}

const saveCurrentFile = async () => {
  if (!currentSkill.value || !selectedPath.value || selectedIsDir.value) return
  savingFile.value = true
  try {
    await skillApi.updateSkillFile(currentSkill.value.slug, {
      path: selectedPath.value,
      content: fileContent.value
    })
    originalFileContent.value = fileContent.value
    message.success('保存成功')
    if (selectedPath.value === 'SKILL.md') {
      await fetchSkills()
    }
  } catch (error) {
    message.error(error.message || '保存失败')
  } finally {
    savingFile.value = false
  }
}

const openCreateModal = (isDir) => {
  if (!currentSkill.value) return
  createForm.path = ''
  createForm.content = ''
  createForm.isDir = isDir
  createModalVisible.value = true
}

const handleCreateNode = async () => {
  if (!currentSkill.value) return
  if (!createForm.path.trim()) {
    message.warning('请输入路径')
    return
  }
  creatingNode.value = true
  try {
    await skillApi.createSkillFile(currentSkill.value.slug, {
      path: createForm.path.trim(),
      is_dir: createForm.isDir,
      content: createForm.content
    })
    createModalVisible.value = false
    await reloadTree()
    message.success(createForm.isDir ? '目录创建成功' : '文件创建成功')
  } catch (error) {
    message.error(error.message || '创建失败')
  } finally {
    creatingNode.value = false
  }
}

const confirmDeleteNode = () => {
  if (!currentSkill.value || !selectedPath.value || selectedPath.value === 'SKILL.md') return
  Modal.confirm({
    title: '确认删除节点？',
    content: selectedPath.value,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    onOk: async () => {
      try {
        await skillApi.deleteSkillFile(currentSkill.value.slug, selectedPath.value)
        resetFileState()
        await reloadTree()
        message.success('删除成功')
      } catch (error) {
        message.error(error.message || '删除失败')
      }
    }
  })
}

const confirmDeleteSkill = () => {
  if (!currentSkill.value) return
  const slug = currentSkill.value.slug
  Modal.confirm({
    title: `确认删除 Skill「${slug}」？`,
    content: '将同时删除技能目录与数据库记录，该操作不可恢复。',
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    onOk: async () => {
      try {
        await skillApi.deleteSkill(slug)
        message.success('Skill 删除成功')
        currentSkill.value = null
        treeData.value = []
        resetFileState()
        await fetchSkills()
      } catch (error) {
        message.error(error.message || '删除 Skill 失败')
      }
    }
  })
}

const getDownloadFilename = (response, fallback) => {
  const header = response.headers.get('content-disposition') || ''
  const match = header.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i)
  if (!match) return fallback
  return decodeURIComponent(match[1] || match[2] || fallback)
}

const handleExport = async () => {
  if (!currentSkill.value) return
  try {
    const response = await skillApi.exportSkill(currentSkill.value.slug)
    const blob = await response.blob()
    const filename = getDownloadFilename(response, `${currentSkill.value.slug}.zip`)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } catch (error) {
    message.error(error.message || '导出失败')
  }
}

const handleImportUpload = async ({ file, onSuccess, onError }) => {
  importing.value = true
  try {
    const result = await skillApi.importSkillZip(file)
    message.success('导入成功')
    await fetchSkills()
    const imported = result?.data
    if (imported?.slug) {
      const record = skills.value.find((item) => item.slug === imported.slug)
      if (record) {
        await selectSkill(record)
      }
    }
    onSuccess?.(result)
  } catch (error) {
    message.error(error.message || '导入失败')
    onError?.(error)
  } finally {
    importing.value = false
  }
}

const saveDependencies = async () => {
  if (!currentSkill.value) return
  savingDependencies.value = true
  try {
    const result = await skillApi.updateSkillDependencies(currentSkill.value.slug, {
      tool_dependencies: dependencyForm.tool_dependencies,
      mcp_dependencies: dependencyForm.mcp_dependencies,
      skill_dependencies: dependencyForm.skill_dependencies
    })
    const updated = result?.data || null
    if (updated) {
      currentSkill.value = updated
      syncDependencyFormFromSkill(updated)
    }
    await fetchSkills()
    message.success('依赖保存成功')
  } catch (error) {
    message.error(error.message || '依赖保存失败')
  } finally {
    savingDependencies.value = false
  }
}

onMounted(() => {
  fetchSkills()
})
</script>

<style scoped lang="less">
.skills-manager {
  padding: 16px;
}

.header-section {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.title {
  margin-bottom: 4px;
}

.description {
  margin: 0;
  color: var(--gray-600);
}

.header-actions {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.content-layout {
  display: grid;
  grid-template-columns: minmax(280px, 36%) 1fr;
  gap: 12px;
}

.skills-list-panel {
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  overflow: hidden;
}

.skill-detail-panel {
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  padding: 10px;
  min-height: 420px;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.detail-title {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.slug {
  color: var(--gray-600);
}

.dependency-summary {
  color: var(--gray-600);
  font-size: 12px;
}

.detail-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.dependency-panel {
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  padding: 8px;
  margin-bottom: 10px;
}

.dependency-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.dependency-title {
  font-weight: 600;
}

.dependency-form :deep(.ant-form-item) {
  margin-bottom: 8px;
}

.detail-body {
  display: grid;
  grid-template-columns: minmax(240px, 35%) 1fr;
  gap: 12px;
}

.tree-panel,
.editor-panel {
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  padding: 8px;
  min-height: 360px;
}

.tree-toolbar,
.editor-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  gap: 8px;
}

.tree-title {
  font-weight: 600;
}

.editor-path {
  color: var(--gray-700);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-editor {
  font-family: Menlo, Monaco, Consolas, 'Courier New', monospace;
}

:deep(.selected-row td) {
  background: var(--gray-100) !important;
}

@media (max-width: 1200px) {
  .content-layout {
    grid-template-columns: 1fr;
  }

  .detail-body {
    grid-template-columns: 1fr;
  }
}
</style>
