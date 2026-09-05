from database import Base
from datetime import datetime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, Table, UniqueConstraint


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

    # Relationship to chats
    chat_topics = relationship("ChatTopic", back_populates="user", cascade="all, delete-orphan")
    chat_histories = relationship("ChatHistory", back_populates="user", cascade="all, delete-orphan")


# Chat History Table
class ChatTopic(Base):
    __tablename__ = "chat_topics"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    title = Column(String(255), nullable=False) # Topic name like "Transit Chairs"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="chat_topics")
    messages = relationship("ChatHistory", back_populates="topic", cascade="all, delete-orphan")


class ChatHistory(Base):
    __tablename__ = "chat_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    topic_id = Column(Integer, ForeignKey("chat_topics.id", ondelete="CASCADE"), nullable=False, index=True)
    
    user_query = Column(Text, nullable=False)
    response_type = Column(String(50))
    response_json = Column(Text)
    products_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="chat_histories")
    topic = relationship("ChatTopic", back_populates="messages")


# Product Visits - how many times product detail page was visited
class ProductSearchCount(Base):
    __tablename__ = "product_search_counts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    search_count = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


# Category Searches - how many times a category was searched / clicked
class CategorySearchCount(Base):
    __tablename__ = "category_search_counts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False, index=True)
    search_count = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class UserSearch(Base):
    __tablename__ = "user_searches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    searched_query = Column(String(500), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())