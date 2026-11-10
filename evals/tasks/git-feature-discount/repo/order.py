from dataclasses import dataclass, field

from customer import Customer


@dataclass
class Order:
    customer: Customer
    lines: list[tuple[str, int, float]] = field(default_factory=list)  # (item, quantity, unit price)

    def add(self, item: str, quantity: int, price: float) -> None:
        self.lines.append((item, quantity, price))

    def total(self) -> float:
        return round(sum(quantity * price for _, quantity, price in self.lines), 2)
