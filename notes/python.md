
```python
from dataclasses import dataclass

# frozen=True：冻结数据类，实例字段不可直接修改、可hash
@dataclass(frozen=True)
class Rect:
    w: int
    h: int

    # @property：计算属性，只读，对外像字段一样访问
    @property
    def area(self) -> int:
        return self.w * self.h


r = Rect(2, 3)
print(r.area)  # 6
# r.w = 10     # FrozenInstanceError，冻结类不能改原始字段
# r.area = 99  # AttributeError，property 默认不可写
```