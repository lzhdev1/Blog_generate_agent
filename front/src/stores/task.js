import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getTask, getTaskList } from '@/api/task'

export const useTaskStore = defineStore('task', () => {
  const currentTask = ref(null)
  const taskList = ref([])
  const loading = ref(false)

  // 获取任务详情
  async function fetchTask(taskId) {
    loading.value = true
    try {
      const res = await getTask(taskId)
      currentTask.value = res
      return res
    } finally {
      loading.value = false
    }
  }

  // 获取任务列表
  async function fetchTaskList() {
    loading.value = true
    try {
      const res = await getTaskList()
      taskList.value = res.tasks || []
      return res
    } finally {
      loading.value = false
    }
  }

  // 设置当前任务
  function setTask(task) {
    currentTask.value = task
  }

  // 清空
  function clear() {
    currentTask.value = null
    taskList.value = []
  }

  return {
    currentTask,
    taskList,
    loading,
    fetchTask,
    fetchTaskList,
    setTask,
    clear
  }
})
