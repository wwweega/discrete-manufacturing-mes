-- MySQL 首次初始化脚本（docker-entrypoint-initdb.d）
-- 业务表由后端启动时通过 SQLAlchemy create_all 自动创建，这里只负责库与字符集。
CREATE DATABASE IF NOT EXISTS `mes`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

ALTER USER 'root'@'%' IDENTIFIED WITH caching_sha2_password BY 'mes123456';
FLUSH PRIVILEGES;
