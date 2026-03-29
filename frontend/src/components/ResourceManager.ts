// AssetManager.ts
// 带过期时间的资源缓存管理器（图片版）

interface CacheEntry {
    element: HTMLImageElement
    expireAt: number
}

interface AssetManagerOptions {
    /**
     * 默认缓存时间（毫秒）
     */
    defaultTTL?: number
}

export class AssetManager {
    private readyMap = new Map<string, CacheEntry>()
    private loadingMap = new Map<string, Promise<void>>()
    private defaultTTL: number

    constructor(options?: AssetManagerOptions) {
        // 默认缓存 5 分钟
        this.defaultTTL = options?.defaultTTL ?? 5 * 60 * 1000
    }

    /**
     * 判断资源是否已就绪（自动处理过期）
     */
    isReady(key: string): boolean {
        const entry = this.readyMap.get(key)
        if (!entry) return false

        // 检查是否过期
        if (Date.now() > entry.expireAt) {
            this.remove(key)
            return false
        }

        return true
    }

    /**
     * 获取资源（自动检查过期）
     */
    get(key: string): HTMLImageElement | undefined {
        if (!this.isReady(key)) return undefined
        return this.readyMap.get(key)?.element
    }

    /**
     * 预加载资源
     * @param key 资源URL
     * @param ttl 可选单独设置缓存时间
     */
    prepare(key: string, ttl?: number): Promise<void> {
        // 已加载且未过期
        if (this.isReady(key)) {
            return Promise.resolve()
        }

        // 正在加载
        if (this.loadingMap.has(key)) {
            return this.loadingMap.get(key)!
        }

        const promise = new Promise<void>((resolve, reject) => {
            const img = new Image()

            img.onload = () => {
                const expireAt = Date.now() + (ttl ?? this.defaultTTL)

                this.readyMap.set(key, {
                    element: img,
                    expireAt
                })

                this.loadingMap.delete(key)
                resolve()
            }

            img.onerror = () => {
                this.loadingMap.delete(key)
                reject(new Error(`Failed to load asset: ${key}`))
            }

            img.src = key
        })

        this.loadingMap.set(key, promise)

        return promise
    }

    /**
     * 手动移除
     */
    remove(key: string) {
        this.readyMap.delete(key)
        this.loadingMap.delete(key)
    }

    /**
     * 清空缓存
     */
    clear() {
        this.readyMap.clear()
        this.loadingMap.clear()
    }

    /**
     * 主动清理过期资源（可选调用）
     */
    sweepExpired() {
        const now = Date.now()

        for (const [key, entry] of this.readyMap.entries()) {
            if (now > entry.expireAt) {
                this.readyMap.delete(key)
            }
        }
    }
}

export interface AssetTask<T = any> {
    id: string
    resourceKeys: string[]
    payload: T
    onReady: (payload: T) => void
}

interface QueueOptions {
    maxConcurrent?: number
    maxQueueSize?: number
}

export class AssetReadyQueue {
    private queue: AssetTask[] = []
    private running = 0
    private taskMap = new Map<string, boolean>()

    private maxConcurrent: number
    private maxQueueSize: number

    constructor(
        private assetManager: AssetManager,
        options?: QueueOptions
    ) {
        this.maxConcurrent = options?.maxConcurrent ?? 3
        this.maxQueueSize = options?.maxQueueSize ?? 500
    }

    /**
     * 添加任务
     */
    enqueue<T>(task: AssetTask<T>) {
        // 防止重复 id
        if (this.taskMap.has(task.id)) return

        if (this.queue.length >= this.maxQueueSize) {
            this.queue.shift()
        }

        this.queue.push(task)
        this.taskMap.set(task.id, true)

        this.process()
    }

    /**
     * 核心调度
     */
    private async process() {
        while (
            this.running < this.maxConcurrent &&
            this.queue.length > 0
        ) {
            const task = this.queue.shift()!
            this.running++

            this.execute(task)
        }
    }

    private async execute(task: AssetTask) {
        try {
            await Promise.all(
                task.resourceKeys.map(key =>
                    this.assetManager.prepare(key)
                )
            )

            task.onReady(task.payload)
        } catch (err) {
            console.warn("Asset load failed:", task.id)
            console.error(err)
        } finally {
            this.running--
            this.taskMap.delete(task.id)
            this.process()
        }
    }

    /**
     * 清空队列
     */
    clear() {
        this.queue = []
        this.taskMap.clear()
    }
}