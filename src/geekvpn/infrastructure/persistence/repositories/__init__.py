"""Repository implementations.

Each one maps between a domain aggregate and its table. The mapping is written
by hand rather than using SQLAlchemy's imperative mapping, because a hand
mapping keeps the domain objects free of ORM machinery - no lazy loading, no
identity map, no accidental query inside a business rule.
"""
