#ifndef RKNN_YOLOV6__BOUNDED_QUEUE_HPP_
#define RKNN_YOLOV6__BOUNDED_QUEUE_HPP_

#include <condition_variable>
#include <cstddef>
#include <memory>
#include <mutex>
#include <queue>
#include <utility>

namespace rknn_yolov6 {

// 以固定容量保存待处理数据，并在队列满时返回被淘汰的最旧数据。
template <typename T>
class BoundedQueue {
public:
    // 创建指定容量的线程安全队列。
    explicit BoundedQueue(std::size_t capacity) : capacity_(capacity) {}

    // 插入新数据；队列满时返回被淘汰的数据，供调用方释放其资源。
    std::shared_ptr<T> push(std::shared_ptr<T> value) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (closed_) {
            return value;
        }

        std::shared_ptr<T> dropped;
        if (queue_.size() >= capacity_) {
            dropped = queue_.front();
            queue_.pop();
        }
        queue_.push(std::move(value));
        condition_.notify_one();
        return dropped;
    }

    // 等待并取出一项；队列关闭且已清空时返回空指针。
    std::shared_ptr<T> wait_and_pop() {
        std::unique_lock<std::mutex> lock(mutex_);
        condition_.wait(lock, [this]() { return closed_ || !queue_.empty(); });
        if (queue_.empty()) {
            return nullptr;
        }
        auto value = queue_.front();
        queue_.pop();
        return value;
    }

    // 关闭队列并唤醒等待线程，使节点可以有序退出。
    void close() {
        std::lock_guard<std::mutex> lock(mutex_);
        closed_ = true;
        condition_.notify_all();
    }

private:
    const std::size_t capacity_;
    std::mutex mutex_;
    std::condition_variable condition_;
    std::queue<std::shared_ptr<T>> queue_;
    bool closed_{false};
};

}  // namespace rknn_yolov6

#endif  // RKNN_YOLOV6__BOUNDED_QUEUE_HPP_
