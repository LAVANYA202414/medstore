from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, Table, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
from datetime import datetime


# Many-to-Many: products <-> categories
product_categories = Table(
    'product_categories',Base.metadata,
    Column('product_id', Integer, ForeignKey('products.id'), primary_key=True),
    Column('category_id', Integer, ForeignKey('categories.id'), primary_key=True)
)

# Product Table
class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(500), nullable=False, index=True)
    slug = Column(String(500), index=True)
    short_description = Column(Text)
    description = Column(Text) # LongDescription
    regular_price = Column(Float, default=0)
    sale_price = Column(Float, default=0)
    in_stock = Column(Boolean, default=True)
    is_featured = Column(Boolean, default=False)
    published = Column(Boolean, default=True)
    visibility = Column(Boolean, default = True)
    brand = Column(String(100), default="Generic")
    model = Column(String(255)) # Attribute 1 value(s)
    images = Column(Text) # store first image url or comma separated
    tags = Column(Text)

    categories = relationship("Category", secondary=product_categories, back_populates="products")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# Category Table
class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), index=True)
    parent_id = Column(Integer, ForeignKey('categories.id'), nullable=True)
    products = relationship("Product", secondary=product_categories, back_populates="categories")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())