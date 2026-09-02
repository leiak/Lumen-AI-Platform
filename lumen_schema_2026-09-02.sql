-- Lumen AI Platform schema dump (DDL only, no data)
-- Generated 2026-09-02T11:54:10
-- Source: localhost:3307  Database: ai_platform
-- Restore:  mysql -h <host> -P <port> -u <user> -p ai_platform < lumen_schema_2026-09-02.sql

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS=0;

USE `ai_platform`;

-- Table: agent_knowledge_bases
DROP TABLE IF EXISTS `agent_knowledge_bases`;
CREATE TABLE `agent_knowledge_bases` (
  `agent_id` int DEFAULT NULL COMMENT '智能体ID',
  `knowledge_base_id` int DEFAULT NULL COMMENT '知识库ID',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_agent_knowledge_bases_id` (`id`),
  KEY `ix_agent_knowledge_bases_knowledge_base_id` (`knowledge_base_id`),
  KEY `ix_agent_knowledge_bases_agent_id` (`agent_id`),
  CONSTRAINT `agent_knowledge_bases_ibfk_1` FOREIGN KEY (`agent_id`) REFERENCES `agents` (`id`),
  CONSTRAINT `agent_knowledge_bases_ibfk_2` FOREIGN KEY (`knowledge_base_id`) REFERENCES `knowledge_bases` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=491 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='智能体知识库多对多关联表';

-- Table: agent_team_members
DROP TABLE IF EXISTS `agent_team_members`;
CREATE TABLE `agent_team_members` (
  `team_id` int DEFAULT NULL COMMENT '团队ID',
  `agent_id` int DEFAULT NULL COMMENT '智能体ID',
  `role` varchar(64) DEFAULT NULL COMMENT '成员角色(如researcher/writer)',
  `priority` int DEFAULT NULL COMMENT '优先级(数字越小优先级越高)',
  `is_active` tinyint(1) DEFAULT NULL COMMENT '是否启用',
  `config` json DEFAULT NULL COMMENT '成员配置(JSON)',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_agent_team_members_agent_id` (`agent_id`),
  KEY `idx_member_team_agent` (`team_id`,`agent_id`),
  KEY `ix_agent_team_members_id` (`id`),
  KEY `ix_agent_team_members_team_id` (`team_id`),
  CONSTRAINT `agent_team_members_ibfk_1` FOREIGN KEY (`team_id`) REFERENCES `agent_teams` (`id`),
  CONSTRAINT `agent_team_members_ibfk_2` FOREIGN KEY (`agent_id`) REFERENCES `agents` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1812 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='智能体团队成员表';

-- Table: agent_team_routes
DROP TABLE IF EXISTS `agent_team_routes`;
CREATE TABLE `agent_team_routes` (
  `team_id` int DEFAULT NULL COMMENT '团队ID',
  `agent_id` int DEFAULT NULL COMMENT '目标智能体ID',
  `keywords` json DEFAULT NULL COMMENT '匹配关键词列表',
  `priority` int DEFAULT NULL COMMENT '优先级',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_agent_team_routes_id` (`id`),
  KEY `ix_agent_team_routes_team_id` (`team_id`),
  KEY `ix_agent_team_routes_agent_id` (`agent_id`),
  CONSTRAINT `agent_team_routes_ibfk_1` FOREIGN KEY (`team_id`) REFERENCES `agent_teams` (`id`),
  CONSTRAINT `agent_team_routes_ibfk_2` FOREIGN KEY (`agent_id`) REFERENCES `agents` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='智能体团队路由规则表(first_match策略)';

-- Table: agent_teams
DROP TABLE IF EXISTS `agent_teams`;
CREATE TABLE `agent_teams` (
  `name` varchar(100) DEFAULT NULL COMMENT '团队名称',
  `description` text COMMENT '团队描述',
  `manager_agent_id` int DEFAULT NULL COMMENT '管理员智能体ID',
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `is_active` tinyint(1) DEFAULT NULL COMMENT '是否启用',
  `route_policy` varchar(32) DEFAULT NULL COMMENT '路由策略(manager_decides/round_robin/first_match)',
  `aggregator_prompt` text COMMENT '聚合器提示词(可选)',
  `config` json DEFAULT NULL COMMENT '团队配置(JSON)',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_agent_teams_manager_agent_id` (`manager_agent_id`),
  KEY `idx_agentteam_tenant_active` (`tenant_id`,`is_active`),
  KEY `ix_agent_teams_tenant_id` (`tenant_id`),
  KEY `ix_agent_teams_id` (`id`),
  CONSTRAINT `agent_teams_ibfk_1` FOREIGN KEY (`manager_agent_id`) REFERENCES `agents` (`id`),
  CONSTRAINT `agent_teams_ibfk_2` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1233 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='多智能体团队表(manager+workers)';

-- Table: agent_tools
DROP TABLE IF EXISTS `agent_tools`;
CREATE TABLE `agent_tools` (
  `agent_id` int DEFAULT NULL COMMENT '智能体ID',
  `tool_name` varchar(100) DEFAULT NULL COMMENT '工具名称',
  `tool_config` json DEFAULT NULL COMMENT '工具配置(JSON)',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_agent_tools_id` (`id`),
  KEY `ix_agent_tools_agent_id` (`agent_id`),
  CONSTRAINT `agent_tools_ibfk_1` FOREIGN KEY (`agent_id`) REFERENCES `agents` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='智能体工具关联表';

-- Table: agents
DROP TABLE IF EXISTS `agents`;
CREATE TABLE `agents` (
  `name` varchar(100) DEFAULT NULL COMMENT '智能体名称',
  `description` text COMMENT '智能体描述',
  `prompt_template` text COMMENT '系统提示词模板',
  `model_name` varchar(50) DEFAULT NULL COMMENT '默认模型名称',
  `temperature` int DEFAULT NULL COMMENT '默认温度参数',
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `is_active` tinyint(1) DEFAULT NULL COMMENT '是否启用',
  `config` json DEFAULT NULL COMMENT '额外配置(JSON)',
  `kb_retrieval_config` json DEFAULT NULL COMMENT '知识库检索配置',
  `memory_policy` varchar(32) DEFAULT NULL COMMENT '记忆策略(none/sliding_window/token_limit/semantic_compression)',
  `memory_window_size` int DEFAULT NULL COMMENT '滑动窗口大小(保留消息条数)',
  `memory_max_tokens` int DEFAULT NULL COMMENT 'Token限制阈值',
  `memory_compression` tinyint(1) DEFAULT NULL COMMENT '是否启用语义压缩',
  `tool_choice` varchar(32) DEFAULT NULL COMMENT '工具选择策略(auto/required/none/specific)',
  `tool_choice_required` tinyint(1) DEFAULT NULL COMMENT '是否强制调用工具',
  `allowed_tools` json DEFAULT NULL COMMENT '允许使用的工具列表(JSON)',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_agents_tenant_id` (`tenant_id`),
  KEY `ix_agents_id` (`id`),
  CONSTRAINT `agents_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=4591 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI智能体配置表';

-- Table: audit_logs
DROP TABLE IF EXISTS `audit_logs`;
CREATE TABLE `audit_logs` (
  `user_id` int DEFAULT NULL COMMENT '操作用户ID',
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `username` varchar(100) DEFAULT NULL COMMENT '操作者用户名',
  `action` varchar(50) DEFAULT NULL COMMENT '操作类型',
  `resource_type` varchar(50) DEFAULT NULL COMMENT '资源类型',
  `resource_id` varchar(100) DEFAULT NULL COMMENT '资源ID',
  `details` json DEFAULT NULL COMMENT '详细信息',
  `ip_address` varchar(50) DEFAULT NULL COMMENT 'IP地址',
  `user_agent` varchar(500) DEFAULT NULL COMMENT 'User-Agent',
  `status` varchar(20) DEFAULT NULL COMMENT '状态(success/failure)',
  `error_message` text COMMENT '错误信息',
  `duration_ms` int DEFAULT NULL COMMENT '操作耗时(毫秒)',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_audit_user_time` (`user_id`,`created_at`),
  KEY `ix_audit_logs_user_id` (`user_id`),
  KEY `idx_audit_action_time` (`action`,`created_at`),
  KEY `idx_audit_tenant_time` (`tenant_id`,`created_at`),
  KEY `ix_audit_logs_tenant_id` (`tenant_id`),
  KEY `ix_audit_logs_id` (`id`),
  CONSTRAINT `audit_logs_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `audit_logs_ibfk_2` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='审计日志表';

-- Table: conversation_memories
DROP TABLE IF EXISTS `conversation_memories`;
CREATE TABLE `conversation_memories` (
  `id` int NOT NULL AUTO_INCREMENT,
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `conversation_id` int DEFAULT NULL COMMENT '对话ID',
  `role` varchar(20) DEFAULT NULL COMMENT '角色(user/assistant)',
  `content` text COMMENT '记忆内容',
  `meta_data` text COMMENT '元数据(JSON字符串)',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_conversation_memories_conversation_id` (`conversation_id`),
  KEY `idx_tenant_conversation` (`tenant_id`,`conversation_id`),
  KEY `ix_conversation_memories_tenant_id` (`tenant_id`),
  KEY `idx_conversation_created` (`conversation_id`,`created_at`),
  CONSTRAINT `conversation_memories_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=107 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='对话记忆持久化表';

-- Table: conversations
DROP TABLE IF EXISTS `conversations`;
CREATE TABLE `conversations` (
  `title` varchar(200) DEFAULT NULL COMMENT '会话标题',
  `user_id` int DEFAULT NULL,
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `agent_id` int DEFAULT NULL COMMENT '关联的智能体ID',
  `team_id` int DEFAULT NULL COMMENT '关联的智能体团队ID',
  `external_app_id` int DEFAULT NULL COMMENT '外部应用ID',
  `external_visitor_id` int DEFAULT NULL COMMENT '外部访客ID',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted_at` datetime DEFAULT NULL COMMENT '软删除时间戳',
  `id` int NOT NULL AUTO_INCREMENT,
  PRIMARY KEY (`id`),
  KEY `tenant_id` (`tenant_id`),
  KEY `agent_id` (`agent_id`),
  KEY `ix_conversations_external_app_id` (`external_app_id`),
  KEY `ix_conversations_external_visitor_id` (`external_visitor_id`),
  KEY `ix_conversations_user_id` (`user_id`),
  KEY `ix_conversations_id` (`id`),
  KEY `ix_conversations_team_id` (`team_id`),
  CONSTRAINT `conversations_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `conversations_ibfk_2` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `conversations_ibfk_3` FOREIGN KEY (`agent_id`) REFERENCES `agents` (`id`),
  CONSTRAINT `conversations_ibfk_4` FOREIGN KEY (`team_id`) REFERENCES `agent_teams` (`id`),
  CONSTRAINT `conversations_ibfk_5` FOREIGN KEY (`external_app_id`) REFERENCES `external_apps` (`id`),
  CONSTRAINT `conversations_ibfk_6` FOREIGN KEY (`external_visitor_id`) REFERENCES `external_visitors` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2290 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='对话会话表';

-- Table: customer_field_definitions
DROP TABLE IF EXISTS `customer_field_definitions`;
CREATE TABLE `customer_field_definitions` (
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `field_key` varchar(50) DEFAULT NULL COMMENT '字段标识键',
  `field_label` varchar(100) DEFAULT NULL COMMENT '字段显示名称',
  `field_type` varchar(20) DEFAULT NULL COMMENT '字段类型(text/number/date/select/multiselect/textarea)',
  `options` json DEFAULT NULL COMMENT '下拉/多选选项列表',
  `required` tinyint(1) DEFAULT NULL COMMENT '是否必填',
  `order_index` int DEFAULT NULL COMMENT '排序索引',
  `is_active` tinyint(1) DEFAULT NULL COMMENT '是否启用',
  `created_by` int DEFAULT NULL COMMENT '创建人用户ID',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_customer_fields_tenant_key` (`tenant_id`,`field_key`),
  KEY `created_by` (`created_by`),
  KEY `idx_customer_fields_tenant_active` (`tenant_id`,`is_active`,`order_index`),
  KEY `ix_customer_field_definitions_tenant_id` (`tenant_id`),
  KEY `ix_customer_field_definitions_id` (`id`),
  CONSTRAINT `customer_field_definitions_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `customer_field_definitions_ibfk_2` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=134 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='客户自定义字段定义表(每租户一份schema)';

-- Table: customer_follow_ups
DROP TABLE IF EXISTS `customer_follow_ups`;
CREATE TABLE `customer_follow_ups` (
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `customer_id` int DEFAULT NULL COMMENT '客户ID',
  `user_id` int DEFAULT NULL COMMENT '跟进人用户ID',
  `follow_up_type` varchar(30) DEFAULT NULL COMMENT '跟进方式(phone/wechat/email/meeting/other)',
  `content` text COMMENT '跟进内容',
  `next_step` text COMMENT '下一步计划',
  `next_follow_up_at` datetime DEFAULT NULL COMMENT '下次跟进时间',
  `ai_suggested` tinyint(1) DEFAULT NULL COMMENT '是否由AI建议触发',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_customer_follow_ups_user_id` (`user_id`),
  KEY `idx_follow_ups_customer_created` (`customer_id`,`created_at`),
  KEY `ix_customer_follow_ups_tenant_id` (`tenant_id`),
  KEY `ix_customer_follow_ups_customer_id` (`customer_id`),
  KEY `ix_customer_follow_ups_id` (`id`),
  KEY `ix_customer_follow_ups_follow_up_type` (`follow_up_type`),
  CONSTRAINT `customer_follow_ups_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `customer_follow_ups_ibfk_2` FOREIGN KEY (`customer_id`) REFERENCES `customers` (`id`) ON DELETE CASCADE,
  CONSTRAINT `customer_follow_ups_ibfk_3` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=475 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='客户跟进记录表(CRM)';

-- Table: customers
DROP TABLE IF EXISTS `customers`;
CREATE TABLE `customers` (
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `owner_user_id` int DEFAULT NULL COMMENT '负责人(销售)用户ID',
  `created_by` int DEFAULT NULL COMMENT '创建人用户ID',
  `name` varchar(100) DEFAULT NULL COMMENT '客户名称',
  `phone` varchar(50) DEFAULT NULL COMMENT '联系电话',
  `email` varchar(200) DEFAULT NULL COMMENT '电子邮箱',
  `wechat` varchar(100) DEFAULT NULL COMMENT '微信号',
  `avatar_url` varchar(500) DEFAULT NULL COMMENT '头像URL',
  `gender` varchar(10) DEFAULT NULL COMMENT '性别(M/F/U)',
  `birthday` date DEFAULT NULL COMMENT '生日',
  `address` varchar(500) DEFAULT NULL COMMENT '地址',
  `company_name` varchar(200) DEFAULT NULL COMMENT '公司名称',
  `company_position` varchar(100) DEFAULT NULL COMMENT '公司职位',
  `industry` varchar(100) DEFAULT NULL COMMENT '所属行业',
  `company_size` varchar(50) DEFAULT NULL COMMENT '公司规模',
  `company_website` varchar(500) DEFAULT NULL COMMENT '公司网站',
  `level` varchar(20) DEFAULT NULL COMMENT '客户级别(vip/normal/potential/lost)',
  `source` varchar(50) DEFAULT NULL COMMENT '客户来源(referral/website/exhibition/ad/other)',
  `tags` json DEFAULT NULL COMMENT '客户标签列表',
  `custom_fields` json DEFAULT NULL COMMENT '自定义字段JSON',
  `remark` text COMMENT '客户备注',
  `last_follow_up_at` datetime DEFAULT NULL COMMENT '最近跟进时间',
  `next_follow_up_at` datetime DEFAULT NULL COMMENT '下次跟进时间',
  `is_active` tinyint(1) DEFAULT NULL COMMENT '是否有效(1=有效,0=无效)',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `created_by` (`created_by`),
  KEY `ix_customers_company_name` (`company_name`),
  KEY `ix_customers_industry` (`industry`),
  KEY `idx_customers_tenant_level` (`tenant_id`,`level`),
  KEY `ix_customers_owner_user_id` (`owner_user_id`),
  KEY `ix_customers_id` (`id`),
  KEY `idx_customers_tenant_next_follow` (`tenant_id`,`next_follow_up_at`),
  KEY `ix_customers_level` (`level`),
  KEY `ix_customers_last_follow_up_at` (`last_follow_up_at`),
  KEY `ix_customers_next_follow_up_at` (`next_follow_up_at`),
  KEY `ix_customers_tenant_id` (`tenant_id`),
  KEY `idx_customers_tenant_owner` (`tenant_id`,`owner_user_id`),
  KEY `idx_customers_tenant_phone` (`tenant_id`,`phone`),
  KEY `idx_customers_tenant_active_updated` (`tenant_id`,`is_active`,`updated_at`),
  KEY `ix_customers_source` (`source`),
  KEY `ix_customers_phone` (`phone`),
  KEY `ix_customers_name` (`name`),
  CONSTRAINT `customers_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `customers_ibfk_2` FOREIGN KEY (`owner_user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `customers_ibfk_3` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=625 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='客户档案主表(CRM)';

-- Table: document_chunks
DROP TABLE IF EXISTS `document_chunks`;
CREATE TABLE `document_chunks` (
  `content` text COMMENT '分块内容',
  `chunk_index` int DEFAULT NULL COMMENT '分块序号',
  `vector_id` varchar(100) DEFAULT NULL COMMENT '向量存储ID(FAISS)',
  `chunk_metadata` json DEFAULT NULL COMMENT '分块元数据',
  `document_id` int DEFAULT NULL COMMENT '所属文档ID',
  `embedding_status` varchar(20) DEFAULT NULL COMMENT '向量状态(ok/failed)',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `modality` varchar(20) NOT NULL DEFAULT 'text' COMMENT 'M38.4: text / image / audio / video',
  `sheet_name` varchar(100) DEFAULT NULL COMMENT 'M38.4: Excel sheet name; NULL for non-Excel',
  `page_number` int DEFAULT NULL COMMENT 'M38.4: PPT/PDF page number; NULL for unpaged',
  `image_caption` text COMMENT 'M38.4: caption used as multimodal embedder input',
  PRIMARY KEY (`id`),
  KEY `ix_document_chunks_document_id` (`document_id`),
  KEY `ix_document_chunks_embedding_status` (`embedding_status`),
  KEY `ix_document_chunks_id` (`id`),
  KEY `ix_document_chunks_vector_id` (`vector_id`),
  CONSTRAINT `document_chunks_ibfk_1` FOREIGN KEY (`document_id`) REFERENCES `documents` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1793 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='文档分块表';

-- Table: document_folders
DROP TABLE IF EXISTS `document_folders`;
CREATE TABLE `document_folders` (
  `knowledge_base_id` int NOT NULL,
  `parent_id` int DEFAULT NULL,
  `name` varchar(100) NOT NULL,
  `description` text,
  `order_index` int NOT NULL,
  `created_by` int DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `created_by` (`created_by`),
  KEY `ix_document_folders_id` (`id`),
  KEY `idx_folders_kb` (`knowledge_base_id`),
  KEY `idx_folders_parent` (`parent_id`),
  KEY `idx_folders_deleted_at` (`deleted_at`),
  CONSTRAINT `document_folders_ibfk_1` FOREIGN KEY (`knowledge_base_id`) REFERENCES `knowledge_bases` (`id`) ON DELETE CASCADE,
  CONSTRAINT `document_folders_ibfk_2` FOREIGN KEY (`parent_id`) REFERENCES `document_folders` (`id`) ON DELETE CASCADE,
  CONSTRAINT `document_folders_ibfk_3` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table: documents
DROP TABLE IF EXISTS `documents`;
CREATE TABLE `documents` (
  `filename` varchar(255) DEFAULT NULL COMMENT '文件名',
  `file_path` varchar(500) DEFAULT NULL COMMENT '文件存储路径',
  `file_type` varchar(100) DEFAULT NULL COMMENT '文件类型(MIME)',
  `file_size` int DEFAULT NULL COMMENT '文件大小(字节)',
  `content` text COMMENT '文档内容文本',
  `doc_metadata` json DEFAULT NULL COMMENT '文档元数据',
  `status` varchar(20) DEFAULT NULL COMMENT '处理状态(pending/processing/completed/failed)',
  `error_message` text COMMENT '错误信息',
  `chunk_count` int DEFAULT NULL COMMENT '分块数量',
  `knowledge_base_id` int DEFAULT NULL COMMENT '所属知识库ID',
  `created_by` int DEFAULT NULL COMMENT '上传用户ID',
  `embedding_model_config_id` int DEFAULT NULL COMMENT 'Embedding模型配置ID',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `folder_id` int DEFAULT NULL COMMENT 'M38.2 folder inside KB; NULL = KB root',
  `asset_storage_key` varchar(500) DEFAULT NULL COMMENT 'M38.1 storage key; NULL on legacy rows',
  `storage_backend` varchar(20) DEFAULT 'local' COMMENT 'M38.1 backend: local / s3; NULL ≡ local',
  `doc_type` varchar(20) NOT NULL DEFAULT 'document' COMMENT 'M38.4: document / image / audio / video',
  `sheet_count` int DEFAULT NULL COMMENT 'M38.4: Excel sheet count; NULL for non-Excel',
  `page_count` int DEFAULT NULL COMMENT 'M38.4: PPT/PDF page count; NULL for unpaged',
  PRIMARY KEY (`id`),
  KEY `ix_documents_embedding_model_config_id` (`embedding_model_config_id`),
  KEY `ix_documents_created_by` (`created_by`),
  KEY `ix_documents_id` (`id`),
  KEY `ix_documents_knowledge_base_id` (`knowledge_base_id`),
  KEY `idx_documents_folder` (`folder_id`),
  KEY `idx_documents_asset_storage_key` (`asset_storage_key`(191)),
  KEY `idx_documents_storage_backend` (`storage_backend`),
  CONSTRAINT `documents_ibfk_1` FOREIGN KEY (`knowledge_base_id`) REFERENCES `knowledge_bases` (`id`),
  CONSTRAINT `documents_ibfk_2` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`),
  CONSTRAINT `documents_ibfk_3` FOREIGN KEY (`embedding_model_config_id`) REFERENCES `model_configs` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `fk_documents_folder` FOREIGN KEY (`folder_id`) REFERENCES `document_folders` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=1148 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='知识库文档表';

-- Table: embedding_call_logs
DROP TABLE IF EXISTS `embedding_call_logs`;
CREATE TABLE `embedding_call_logs` (
  `call_id` varchar(36) DEFAULT NULL COMMENT '调用ID(UUID)',
  `parent_call_id` varchar(36) DEFAULT NULL COMMENT '父调用ID',
  `trace_id` varchar(36) DEFAULT NULL COMMENT '追踪ID',
  `call_type` varchar(64) DEFAULT NULL COMMENT '调用类型(kb_retrieval/kb_ingest/dim_probe/workflow_kb)',
  `call_index` int DEFAULT NULL COMMENT '调用序号',
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `user_id` int DEFAULT NULL COMMENT '触发用户ID',
  `username` varchar(100) DEFAULT NULL COMMENT '触发用户名',
  `client_app` varchar(50) DEFAULT NULL COMMENT '客户端应用',
  `conversation_id` int DEFAULT NULL COMMENT '对话ID',
  `agent_id` int DEFAULT NULL COMMENT '智能体ID',
  `team_id` int DEFAULT NULL COMMENT '团队ID',
  `workflow_id` int DEFAULT NULL COMMENT '工作流ID',
  `workflow_run_id` int DEFAULT NULL COMMENT '工作流运行ID',
  `workflow_node_id` varchar(64) DEFAULT NULL COMMENT '工作流节点ID',
  `knowledge_base_id` int DEFAULT NULL COMMENT '知识库ID',
  `model_type` varchar(50) DEFAULT NULL COMMENT '模型类型',
  `model_name` varchar(100) DEFAULT NULL COMMENT '模型名称',
  `model_config_id` int DEFAULT NULL COMMENT '模型配置ID',
  `text_preview` varchar(200) DEFAULT NULL COMMENT '文本预览(前200字符)',
  `text_chars` int DEFAULT NULL COMMENT '文本字符数',
  `is_batch` tinyint(1) DEFAULT NULL COMMENT '是否批量调用',
  `batch_size` int DEFAULT NULL COMMENT '批量大小',
  `embedding_dim` int DEFAULT NULL COMMENT '向量维度',
  `embedding_bytes` int DEFAULT NULL COMMENT '向量字节数',
  `started_at` datetime DEFAULT NULL COMMENT '开始时间',
  `finished_at` datetime DEFAULT NULL COMMENT '结束时间',
  `duration_ms` int DEFAULT NULL COMMENT '耗时(毫秒)',
  `status` varchar(20) DEFAULT NULL COMMENT '状态',
  `error_type` varchar(100) DEFAULT NULL COMMENT '错误类型',
  `error_message` text COMMENT '错误信息',
  `retry_count` int DEFAULT NULL COMMENT '重试次数',
  `request_ip` varchar(50) DEFAULT NULL COMMENT '请求IP',
  `user_agent` varchar(500) DEFAULT NULL COMMENT 'User-Agent',
  `extra` json DEFAULT NULL COMMENT '额外数据',
  `archived_at` datetime DEFAULT NULL COMMENT '归档时间',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_embedding_call_logs_call_id` (`call_id`),
  KEY `ix_embedding_call_logs_workflow_run_id` (`workflow_run_id`),
  KEY `idx_ecl_status_time` (`status`,`created_at`),
  KEY `ix_embedding_call_logs_user_id` (`user_id`),
  KEY `idx_ecl_call_type_time` (`call_type`,`created_at`),
  KEY `ix_embedding_call_logs_agent_id` (`agent_id`),
  KEY `ix_embedding_call_logs_workflow_id` (`workflow_id`),
  KEY `ix_embedding_call_logs_conversation_id` (`conversation_id`),
  KEY `ix_embedding_call_logs_status` (`status`),
  KEY `ix_embedding_call_logs_trace_id` (`trace_id`),
  KEY `ix_embedding_call_logs_tenant_id` (`tenant_id`),
  KEY `ix_embedding_call_logs_knowledge_base_id` (`knowledge_base_id`),
  KEY `ix_embedding_call_logs_model_config_id` (`model_config_id`),
  KEY `idx_ecl_model_time` (`model_config_id`,`created_at`),
  KEY `ix_embedding_call_logs_parent_call_id` (`parent_call_id`),
  KEY `ix_embedding_call_logs_team_id` (`team_id`),
  KEY `idx_ecl_tenant_time` (`tenant_id`,`created_at`),
  KEY `ix_embedding_call_logs_id` (`id`),
  KEY `idx_ecl_kb` (`knowledge_base_id`,`created_at`),
  KEY `idx_ecl_trace` (`trace_id`,`call_index`),
  CONSTRAINT `embedding_call_logs_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `embedding_call_logs_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `embedding_call_logs_ibfk_3` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`),
  CONSTRAINT `embedding_call_logs_ibfk_4` FOREIGN KEY (`agent_id`) REFERENCES `agents` (`id`),
  CONSTRAINT `embedding_call_logs_ibfk_5` FOREIGN KEY (`team_id`) REFERENCES `agent_teams` (`id`),
  CONSTRAINT `embedding_call_logs_ibfk_6` FOREIGN KEY (`workflow_id`) REFERENCES `workflows` (`id`),
  CONSTRAINT `embedding_call_logs_ibfk_7` FOREIGN KEY (`workflow_run_id`) REFERENCES `workflow_runs` (`id`),
  CONSTRAINT `embedding_call_logs_ibfk_8` FOREIGN KEY (`knowledge_base_id`) REFERENCES `knowledge_bases` (`id`),
  CONSTRAINT `embedding_call_logs_ibfk_9` FOREIGN KEY (`model_config_id`) REFERENCES `model_configs` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1356 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Embedding调用日志表(可观测性)';

-- Table: eval_dataset_items
DROP TABLE IF EXISTS `eval_dataset_items`;
CREATE TABLE `eval_dataset_items` (
  `dataset_id` int NOT NULL COMMENT '父 dataset,CASCADE 删除',
  `query` text NOT NULL COMMENT '评测 query,纯文本',
  `expected_doc_ids` json NOT NULL COMMENT '期望命中的 document_id 列表,JSON 数组',
  `expected_answer` text COMMENT 'ground truth 答案,可选,LLM judge 用',
  `answer_keywords` json DEFAULT NULL COMMENT '期望答案关键词,JSON 字符串数组,keyword_hit_rate 用',
  `category` varchar(64) DEFAULT NULL COMMENT 'factual | reasoning | multi_hop | keyword_heavy | out_of_scope',
  `difficulty` varchar(20) DEFAULT NULL COMMENT 'easy | medium | hard',
  `notes` text COMMENT '研发 / QA 备注',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_eval_dataset_items_dataset_id` (`dataset_id`),
  KEY `ix_eval_dataset_items_id` (`id`),
  KEY `ix_eval_dataset_items_category` (`category`),
  KEY `ix_eval_dataset_items_ds_category` (`dataset_id`,`category`),
  CONSTRAINT `eval_dataset_items_ibfk_1` FOREIGN KEY (`dataset_id`) REFERENCES `eval_datasets` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=3324 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table: eval_datasets
DROP TABLE IF EXISTS `eval_datasets`;
CREATE TABLE `eval_datasets` (
  `kb_id` int NOT NULL COMMENT '关联知识库 ID,CASCADE 删除',
  `tenant_id` int DEFAULT NULL COMMENT 'NULL = 全局 builtin,数字 = 私有 tenant',
  `name` varchar(200) NOT NULL,
  `description` text,
  `source` varchar(20) NOT NULL COMMENT 'manual | imported | synthetic',
  `is_active` int NOT NULL COMMENT '1 启用 / 0 停用',
  `created_by` int DEFAULT NULL COMMENT 'NULL = 内置种子数据集',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `created_by` (`created_by`),
  KEY `ix_eval_datasets_kb_id` (`kb_id`),
  KEY `ix_eval_datasets_kb_active` (`kb_id`,`is_active`),
  KEY `ix_eval_datasets_tenant_id` (`tenant_id`),
  KEY `ix_eval_datasets_id` (`id`),
  CONSTRAINT `eval_datasets_ibfk_1` FOREIGN KEY (`kb_id`) REFERENCES `knowledge_bases` (`id`) ON DELETE CASCADE,
  CONSTRAINT `eval_datasets_ibfk_2` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE SET NULL,
  CONSTRAINT `eval_datasets_ibfk_3` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=1441 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table: eval_run_results
DROP TABLE IF EXISTS `eval_run_results`;
CREATE TABLE `eval_run_results` (
  `run_id` int NOT NULL COMMENT '关联 eval_runs.id;run 删了 CASCADE 清 results',
  `item_id` int NOT NULL COMMENT '关联 eval_dataset_items.id;item 删了 CASCADE 清 results',
  `query` text NOT NULL COMMENT '评测当时的 query 文本(冗余)',
  `retrieved_doc_ids` json NOT NULL COMMENT '实际检索命中的 document id 列表(JSON list[int])',
  `retrieval_scores` json NOT NULL COMMENT '每个 doc 的 score(JSON list[float]),与 retrieved_doc_ids 同序',
  `retrieved_contexts` json DEFAULT NULL COMMENT '截断后的 chunk text 列表(≤ 200 字/个),供 audit + judge faithfulness',
  `answer` text COMMENT 'LLM 生成的最终答案(RAG 拼装);None = answer 阶段失败',
  `retrieval_metrics` json NOT NULL COMMENT '检索指标:hit_at_5/10, mrr, ndcg_at_10, recall_at_10',
  `answer_metrics` json DEFAULT NULL COMMENT '答案指标:faithfulness/answer_relevancy(0/1/2)+ keyword_hit_rate(0~1)',
  `llm_judge_calls` json DEFAULT NULL COMMENT 'judge LLM 调用详情(供 audit / faithfulness=0 时回看 reasoning)',
  `latency_ms` int DEFAULT NULL COMMENT '单条 item 总耗时(retrieval + answer + judge),report 用 p50/p95',
  `embedding_call_log_ids` json DEFAULT NULL COMMENT '本次检索期间的 EmbeddingCallLog 行 id 列表(跳转 trace 用)',
  `error_message` text COMMENT '单条 item 跑崩时的 root cause;run.status 仍 completed 但本行失败',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_eval_run_results_id` (`id`),
  KEY `ix_eval_run_results_item_id` (`item_id`),
  KEY `ix_eval_run_results_run_id` (`run_id`),
  KEY `idx_eval_result_run_item` (`run_id`,`item_id`),
  CONSTRAINT `eval_run_results_ibfk_1` FOREIGN KEY (`run_id`) REFERENCES `eval_runs` (`id`) ON DELETE CASCADE,
  CONSTRAINT `eval_run_results_ibfk_2` FOREIGN KEY (`item_id`) REFERENCES `eval_dataset_items` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=1780 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table: eval_runs
DROP TABLE IF EXISTS `eval_runs`;
CREATE TABLE `eval_runs` (
  `dataset_id` int NOT NULL COMMENT '绑定的 eval_datasets.id;dataset 删除时 CASCADE 清 run + results',
  `config_json` json NOT NULL COMMENT '评测参数全集(JSON),含 search_weights / top_k / rerank / judge model 等',
  `status` varchar(20) NOT NULL COMMENT 'pending / running / completed / failed / cancelled',
  `total_items` int NOT NULL,
  `completed_items` int NOT NULL,
  `metrics_json` json DEFAULT NULL COMMENT '整体聚合指标;所有 results 写完后由 report.py 一次性生成',
  `report_markdown` text COMMENT '自动生成的 Markdown 报告,≤ 50KB;dashboard 直接渲染',
  `error_message` text COMMENT 'status=failed 时的 root cause,前端展示',
  `started_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `created_by` int DEFAULT NULL COMMENT '触发此 run 的 user id;user 删了保留 run(SET NULL)',
  `trace_id` varchar(36) DEFAULT NULL COMMENT '关联 LLMCallLog/EmbeddingCallLog 的 trace_id',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `created_by` (`created_by`),
  KEY `ix_eval_runs_dataset_id` (`dataset_id`),
  KEY `ix_eval_runs_trace_id` (`trace_id`),
  KEY `ix_eval_runs_id` (`id`),
  KEY `idx_eval_run_status_time` (`status`,`created_at`),
  KEY `idx_eval_run_ds_time` (`dataset_id`,`created_at`),
  CONSTRAINT `eval_runs_ibfk_1` FOREIGN KEY (`dataset_id`) REFERENCES `eval_datasets` (`id`) ON DELETE CASCADE,
  CONSTRAINT `eval_runs_ibfk_2` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=1087 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table: external_apps
DROP TABLE IF EXISTS `external_apps`;
CREATE TABLE `external_apps` (
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `name` varchar(100) DEFAULT NULL COMMENT '应用名称',
  `app_key` varchar(64) DEFAULT NULL COMMENT '应用Key(唯一标识)',
  `app_secret_hash` varchar(255) DEFAULT NULL COMMENT '应用密钥Hash(bcrypt)',
  `allowed_origins` json DEFAULT NULL COMMENT '允许的源地址列表',
  `allowed_agent_ids` json DEFAULT NULL COMMENT '允许的智能体ID列表',
  `allowed_team_ids` json DEFAULT NULL COMMENT '允许的团队ID列表',
  `scopes` varchar(255) DEFAULT NULL COMMENT '授权范围',
  `rate_limit_per_min` int DEFAULT NULL COMMENT '每分钟限流',
  `is_active` tinyint(1) DEFAULT NULL COMMENT '是否启用',
  `description` text COMMENT '应用描述',
  `created_by` int DEFAULT NULL COMMENT '创建人用户ID',
  `last_used_at` datetime DEFAULT NULL COMMENT '最后使用时间',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `app_key` (`app_key`),
  KEY `created_by` (`created_by`),
  KEY `ix_external_apps_tenant_active` (`tenant_id`,`is_active`),
  KEY `ix_external_apps_tenant_id` (`tenant_id`),
  KEY `ix_external_apps_id` (`id`),
  KEY `ix_external_apps_tenant_created` (`tenant_id`,`created_at` DESC),
  CONSTRAINT `external_apps_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `external_apps_ibfk_2` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=559 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='外部应用配置表(嵌入式聊天组件)';

-- Table: external_visitors
DROP TABLE IF EXISTS `external_visitors`;
CREATE TABLE `external_visitors` (
  `app_id` int DEFAULT NULL COMMENT '所属应用ID',
  `visitor_id` varchar(64) DEFAULT NULL COMMENT '访客ID(UUID)',
  `display_name` varchar(100) DEFAULT NULL COMMENT '显示名称',
  `visitor_metadata` json DEFAULT NULL COMMENT '访客元数据',
  `first_seen_at` datetime DEFAULT NULL COMMENT '首次访问时间',
  `last_seen_at` datetime DEFAULT NULL COMMENT '最后访问时间',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_external_visitors_app_visitor` (`app_id`,`visitor_id`),
  KEY `ix_external_visitors_id` (`id`),
  KEY `ix_external_visitors_app_id` (`app_id`),
  KEY `ix_external_visitors_app_lastseen` (`app_id`,`last_seen_at` DESC),
  CONSTRAINT `external_visitors_ibfk_1` FOREIGN KEY (`app_id`) REFERENCES `external_apps` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=794 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='外部访客表(嵌入式聊天组件)';

-- Table: faq_entries
DROP TABLE IF EXISTS `faq_entries`;
CREATE TABLE `faq_entries` (
  `knowledge_base_id` int DEFAULT NULL COMMENT '所属知识库ID',
  `question` text COMMENT '问题',
  `answer` text COMMENT '答案',
  `category` varchar(50) DEFAULT NULL COMMENT '分类',
  `tags` json DEFAULT NULL COMMENT '标签列表',
  `vector_id` varchar(100) DEFAULT NULL COMMENT '向量存储ID',
  `document_id` int DEFAULT NULL COMMENT '关联虚拟文档ID',
  `chunk_id` int DEFAULT NULL COMMENT '关联分块ID',
  `embedding_model_config_id` int DEFAULT NULL COMMENT 'Embedding模型配置ID',
  `created_by` int DEFAULT NULL COMMENT '创建人用户ID',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `document_id` (`document_id`),
  KEY `chunk_id` (`chunk_id`),
  KEY `embedding_model_config_id` (`embedding_model_config_id`),
  KEY `created_by` (`created_by`),
  KEY `ix_faq_entries_knowledge_base_id` (`knowledge_base_id`),
  KEY `ix_faq_entries_id` (`id`),
  KEY `ix_faq_entries_category` (`category`),
  KEY `ix_faq_entries_kb` (`knowledge_base_id`),
  KEY `ix_faq_entries_kb_category` (`knowledge_base_id`,`category`),
  CONSTRAINT `faq_entries_ibfk_1` FOREIGN KEY (`knowledge_base_id`) REFERENCES `knowledge_bases` (`id`) ON DELETE CASCADE,
  CONSTRAINT `faq_entries_ibfk_2` FOREIGN KEY (`document_id`) REFERENCES `documents` (`id`) ON DELETE CASCADE,
  CONSTRAINT `faq_entries_ibfk_3` FOREIGN KEY (`chunk_id`) REFERENCES `document_chunks` (`id`) ON DELETE CASCADE,
  CONSTRAINT `faq_entries_ibfk_4` FOREIGN KEY (`embedding_model_config_id`) REFERENCES `model_configs` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `faq_entries_ibfk_5` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=943 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='知识库FAQ问答表';

-- Table: generated_audios
DROP TABLE IF EXISTS `generated_audios`;
CREATE TABLE `generated_audios` (
  `tenant_id` int NOT NULL,
  `user_id` int NOT NULL,
  `conversation_id` int DEFAULT NULL,
  `model_config_id` int NOT NULL,
  `playbook_id` int DEFAULT NULL,
  `text` text NOT NULL,
  `voice` varchar(100) NOT NULL,
  `speed` varchar(10) NOT NULL,
  `format` varchar(10) NOT NULL,
  `params` json DEFAULT NULL,
  `file_path` varchar(500) NOT NULL,
  `file_size` int NOT NULL,
  `mime_type` varchar(50) NOT NULL,
  `duration_ms` int DEFAULT NULL,
  `char_count` int NOT NULL,
  `cost_usd` varchar(20) DEFAULT NULL,
  `status` varchar(20) NOT NULL,
  `error_message` text,
  `started_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_generated_audios_tenant_id` (`tenant_id`),
  KEY `ix_gen_audios_tenant_status_created` (`tenant_id`,`status`,`created_at`),
  KEY `ix_generated_audios_model_config_id` (`model_config_id`),
  KEY `ix_generated_audios_conversation_id` (`conversation_id`),
  KEY `ix_generated_audios_user_id` (`user_id`),
  KEY `ix_generated_audios_id` (`id`),
  KEY `ix_generated_audios_playbook_id` (`playbook_id`),
  CONSTRAINT `generated_audios_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `generated_audios_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `generated_audios_ibfk_3` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`),
  CONSTRAINT `generated_audios_ibfk_4` FOREIGN KEY (`model_config_id`) REFERENCES `model_configs` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `generated_audios_ibfk_5` FOREIGN KEY (`playbook_id`) REFERENCES `playbooks` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=347 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table: generated_images
DROP TABLE IF EXISTS `generated_images`;
CREATE TABLE `generated_images` (
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `user_id` int DEFAULT NULL COMMENT '用户ID',
  `model_config_id` int DEFAULT NULL COMMENT '模型配置ID',
  `batch_id` varchar(36) DEFAULT NULL COMMENT '批次ID',
  `prompt` text COMMENT '正向提示词',
  `negative_prompt` text COMMENT '负向提示词',
  `size` varchar(20) DEFAULT NULL COMMENT '图像尺寸',
  `n` int DEFAULT NULL COMMENT '生成数量',
  `quality` varchar(20) DEFAULT NULL COMMENT '图像质量',
  `style` varchar(20) DEFAULT NULL COMMENT '图像风格',
  `params` json DEFAULT NULL COMMENT '额外参数',
  `file_path` varchar(500) DEFAULT NULL COMMENT '文件路径',
  `file_size` int DEFAULT NULL COMMENT '文件大小(字节)',
  `mime_type` varchar(50) DEFAULT NULL COMMENT 'MIME类型',
  `width` int DEFAULT NULL COMMENT '图像宽度',
  `height` int DEFAULT NULL COMMENT '图像高度',
  `thumbnail` mediumblob COMMENT '缩略图',
  `status` varchar(20) DEFAULT NULL COMMENT '状态(pending/generating/completed/failed)',
  `error_message` text COMMENT '错误信息',
  `duration_ms` int DEFAULT NULL COMMENT '生成耗时(毫秒)',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_generated_images_tenant_id` (`tenant_id`),
  KEY `ix_generated_images_model_config_id` (`model_config_id`),
  KEY `ix_generated_images_batch_id` (`batch_id`),
  KEY `ix_generated_images_id` (`id`),
  KEY `ix_gen_images_tenant_status_created` (`tenant_id`,`status`,`created_at`),
  KEY `ix_generated_images_user_id` (`user_id`),
  CONSTRAINT `generated_images_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `generated_images_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `generated_images_ibfk_3` FOREIGN KEY (`model_config_id`) REFERENCES `model_configs` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB AUTO_INCREMENT=1013 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI图像生成记录表';

-- Table: generated_videos
DROP TABLE IF EXISTS `generated_videos`;
CREATE TABLE `generated_videos` (
  `tenant_id` int NOT NULL,
  `user_id` int NOT NULL,
  `conversation_id` int DEFAULT NULL,
  `model_config_id` int DEFAULT NULL,
  `playbook_id` int DEFAULT NULL,
  `source_audio_id` int DEFAULT NULL,
  `source_subtitle_id` int DEFAULT NULL,
  `source_images` json DEFAULT NULL,
  `resolution` varchar(20) NOT NULL,
  `fps` int NOT NULL,
  `params` json DEFAULT NULL,
  `file_path` varchar(500) NOT NULL,
  `file_size` int NOT NULL,
  `mime_type` varchar(50) NOT NULL,
  `duration_ms` int DEFAULT NULL,
  `thumbnail` mediumblob,
  `status` varchar(20) NOT NULL,
  `error_message` text,
  `started_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_gen_videos_tenant_status_created` (`tenant_id`,`status`,`created_at`),
  KEY `ix_generated_videos_tenant_id` (`tenant_id`),
  KEY `ix_generated_videos_playbook_id` (`playbook_id`),
  KEY `ix_generated_videos_source_audio_id` (`source_audio_id`),
  KEY `ix_generated_videos_source_subtitle_id` (`source_subtitle_id`),
  KEY `ix_generated_videos_conversation_id` (`conversation_id`),
  KEY `ix_generated_videos_model_config_id` (`model_config_id`),
  KEY `ix_generated_videos_user_id` (`user_id`),
  KEY `ix_generated_videos_id` (`id`),
  CONSTRAINT `generated_videos_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `generated_videos_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `generated_videos_ibfk_3` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`),
  CONSTRAINT `generated_videos_ibfk_4` FOREIGN KEY (`model_config_id`) REFERENCES `model_configs` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `generated_videos_ibfk_5` FOREIGN KEY (`playbook_id`) REFERENCES `playbooks` (`id`),
  CONSTRAINT `generated_videos_ibfk_6` FOREIGN KEY (`source_audio_id`) REFERENCES `generated_audios` (`id`) ON DELETE SET NULL,
  CONSTRAINT `generated_videos_ibfk_7` FOREIGN KEY (`source_subtitle_id`) REFERENCES `subtitles` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=317 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table: global_memories
DROP TABLE IF EXISTS `global_memories`;
CREATE TABLE `global_memories` (
  `id` int NOT NULL AUTO_INCREMENT,
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `conversation_id` int DEFAULT NULL COMMENT '来源对话ID(可选)',
  `role` varchar(20) DEFAULT NULL COMMENT '角色(user/assistant)',
  `content` text COMMENT '记忆内容',
  `meta_data` text COMMENT '元数据(JSON字符串)',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_global_tenant_conv_created` (`tenant_id`,`conversation_id`,`created_at`),
  KEY `idx_global_tenant_created` (`tenant_id`,`created_at`),
  KEY `ix_global_memories_tenant_id` (`tenant_id`),
  CONSTRAINT `global_memories_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=357 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='全局记忆表(跨对话共享)';

-- Table: image_assets
DROP TABLE IF EXISTS `image_assets`;
CREATE TABLE `image_assets` (
  `document_id` int NOT NULL COMMENT 'Source Document.id; CASCADE on delete',
  `chunk_id` int DEFAULT NULL COMMENT 'DocumentChunk.id (modality=''image''); SET NULL on delete',
  `original_doc_page` int DEFAULT NULL COMMENT 'Source page when extracted from PPT/PDF; NULL = standalone upload',
  `storage_key` varchar(500) NOT NULL COMMENT 'Storage backend key (relative for local, s3 key for S3)',
  `width` int DEFAULT NULL,
  `height` int DEFAULT NULL,
  `mime_type` varchar(50) DEFAULT NULL,
  `file_size` int DEFAULT NULL,
  `caption` text COMMENT 'Multimodal embedder input text',
  `embedding_status` varchar(20) NOT NULL COMMENT 'pending / ok / failed; mirrors DocumentChunk.embedding_status',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_image_assets_document_id` (`document_id`),
  KEY `ix_image_assets_id` (`id`),
  KEY `ix_image_assets_chunk_id` (`chunk_id`),
  KEY `idx_image_assets_doc_created` (`document_id`,`created_at`),
  CONSTRAINT `image_assets_ibfk_1` FOREIGN KEY (`document_id`) REFERENCES `documents` (`id`) ON DELETE CASCADE,
  CONSTRAINT `image_assets_ibfk_2` FOREIGN KEY (`chunk_id`) REFERENCES `document_chunks` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table: installed_skills
DROP TABLE IF EXISTS `installed_skills`;
CREATE TABLE `installed_skills` (
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `marketplace_skill_id` int DEFAULT NULL COMMENT '技能市场ID',
  `skill_id` int DEFAULT NULL COMMENT '关联技能ID',
  `status` varchar(20) DEFAULT NULL COMMENT '状态(active/inactive/error)',
  `installed_at` datetime DEFAULT NULL COMMENT '安装时间',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_installed_tenant_marketplace` (`tenant_id`,`marketplace_skill_id`),
  KEY `marketplace_skill_id` (`marketplace_skill_id`),
  KEY `skill_id` (`skill_id`),
  KEY `ix_installed_skills_id` (`id`),
  KEY `ix_installed_skills_tenant_id` (`tenant_id`),
  CONSTRAINT `installed_skills_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `installed_skills_ibfk_2` FOREIGN KEY (`marketplace_skill_id`) REFERENCES `skill_marketplace` (`id`),
  CONSTRAINT `installed_skills_ibfk_3` FOREIGN KEY (`skill_id`) REFERENCES `skills` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2195 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='租户已安装技能表';

-- Table: knowledge_bases
DROP TABLE IF EXISTS `knowledge_bases`;
CREATE TABLE `knowledge_bases` (
  `name` varchar(100) DEFAULT NULL COMMENT '知识库名称',
  `description` text COMMENT '知识库描述',
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `embedding_model` varchar(50) DEFAULT NULL COMMENT 'Embedding模型名称',
  `embedding_model_config_id` int DEFAULT NULL COMMENT 'Embedding模型配置ID',
  `status` varchar(20) DEFAULT NULL COMMENT '状态(active/inactive)',
  `search_weights` json DEFAULT NULL COMMENT '混合搜索权重配置',
  `default_parser` varchar(20) DEFAULT NULL COMMENT '默认解析器',
  `chunk_size` int DEFAULT NULL COMMENT '分块大小',
  `chunk_overlap` int DEFAULT NULL COMMENT '分块重叠大小',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `workspace_id` int DEFAULT NULL COMMENT 'M38.2 navigation root; NULL = tenant root',
  `multimodal_enabled` int NOT NULL DEFAULT '0' COMMENT 'M38.4: 0 = text-only; 1 = multimodal',
  `multimodal_config_id` int DEFAULT NULL COMMENT 'M38.4: multimodal embedding config id; NULL until selected',
  PRIMARY KEY (`id`),
  KEY `ix_knowledge_bases_embedding_model_config_id` (`embedding_model_config_id`),
  KEY `ix_knowledge_bases_id` (`id`),
  KEY `ix_knowledge_bases_tenant_id` (`tenant_id`),
  KEY `idx_kb_workspace` (`workspace_id`),
  KEY `idx_kb_multimodal_config` (`multimodal_config_id`),
  CONSTRAINT `fk_kb_multimodal_config` FOREIGN KEY (`multimodal_config_id`) REFERENCES `multimodal_embedding_configs` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_kb_workspace` FOREIGN KEY (`workspace_id`) REFERENCES `workspaces` (`id`) ON DELETE SET NULL,
  CONSTRAINT `knowledge_bases_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `knowledge_bases_ibfk_2` FOREIGN KEY (`embedding_model_config_id`) REFERENCES `model_configs` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB AUTO_INCREMENT=2920 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='知识库表';

-- Table: llm_call_logs
DROP TABLE IF EXISTS `llm_call_logs`;
CREATE TABLE `llm_call_logs` (
  `call_id` varchar(36) DEFAULT NULL COMMENT '调用ID(UUID)',
  `parent_call_id` varchar(36) DEFAULT NULL COMMENT '父调用ID',
  `trace_id` varchar(36) DEFAULT NULL COMMENT '追踪ID',
  `call_type` varchar(64) DEFAULT NULL COMMENT '调用类型',
  `call_index` int DEFAULT NULL COMMENT '调用序号',
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `user_id` int DEFAULT NULL COMMENT '触发用户ID',
  `username` varchar(100) DEFAULT NULL COMMENT '触发用户名',
  `client_app` varchar(50) DEFAULT NULL COMMENT '客户端应用',
  `conversation_id` int DEFAULT NULL COMMENT '对话ID',
  `message_id` int DEFAULT NULL COMMENT '消息ID',
  `agent_id` int DEFAULT NULL COMMENT '智能体ID',
  `team_id` int DEFAULT NULL COMMENT '团队ID',
  `team_member_id` int DEFAULT NULL COMMENT '团队成员ID',
  `workflow_id` int DEFAULT NULL COMMENT '工作流ID',
  `workflow_run_id` int DEFAULT NULL COMMENT '工作流运行ID',
  `workflow_node_id` varchar(64) DEFAULT NULL COMMENT '工作流节点ID',
  `image_id` int DEFAULT NULL COMMENT '图像生成ID',
  `model_type` varchar(50) DEFAULT NULL COMMENT '模型类型',
  `model_name` varchar(100) DEFAULT NULL COMMENT '模型名称',
  `model_config_id` int DEFAULT NULL COMMENT '模型配置ID',
  `temperature` float DEFAULT NULL COMMENT '温度参数',
  `max_tokens` int DEFAULT NULL COMMENT '最大Token数',
  `system_messages` json DEFAULT NULL COMMENT '系统消息列表',
  `user_message` text COMMENT '用户消息',
  `messages` json DEFAULT NULL COMMENT '完整消息历史',
  `tools` json DEFAULT NULL COMMENT '工具定义',
  `extra_params` json DEFAULT NULL COMMENT '额外参数',
  `input_chars` int DEFAULT NULL COMMENT '输入字符数',
  `input_tokens_estimate` int DEFAULT NULL COMMENT '输入Token估算',
  `response_content` text COMMENT '响应内容',
  `finish_reason` varchar(50) DEFAULT NULL COMMENT '结束原因',
  `tool_calls` json DEFAULT NULL COMMENT '工具调用列表',
  `output_chars` int DEFAULT NULL COMMENT '输出字符数',
  `output_tokens_estimate` int DEFAULT NULL COMMENT '输出Token估算',
  `token_usage` json DEFAULT NULL COMMENT 'Token用量统计',
  `started_at` datetime DEFAULT NULL COMMENT '开始时间',
  `finished_at` datetime DEFAULT NULL COMMENT '结束时间',
  `duration_ms` int DEFAULT NULL COMMENT '耗时(毫秒)',
  `first_token_latency_ms` int DEFAULT NULL COMMENT '首Token延迟(毫秒)',
  `status` varchar(20) DEFAULT NULL COMMENT '状态(success/failure)',
  `error_type` varchar(100) DEFAULT NULL COMMENT '错误类型',
  `error_message` text COMMENT '错误信息',
  `retry_count` int DEFAULT NULL COMMENT '重试次数',
  `request_ip` varchar(50) DEFAULT NULL COMMENT '请求IP',
  `user_agent` varchar(500) DEFAULT NULL COMMENT 'User-Agent',
  `extra` json DEFAULT NULL COMMENT '额外数据',
  `archived_at` datetime DEFAULT NULL COMMENT '归档时间',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_llm_call_logs_call_id` (`call_id`),
  KEY `ix_llm_call_logs_model_config_id` (`model_config_id`),
  KEY `idx_lcl_module_time` (`call_type`,`created_at`),
  KEY `ix_llm_call_logs_image_id` (`image_id`),
  KEY `ix_llm_call_logs_message_id` (`message_id`),
  KEY `ix_llm_call_logs_team_id` (`team_id`),
  KEY `idx_lcl_tenant_time` (`tenant_id`,`created_at`),
  KEY `ix_llm_call_logs_status` (`status`),
  KEY `idx_lcl_model_time` (`model_name`,`created_at`),
  KEY `ix_llm_call_logs_tenant_id` (`tenant_id`),
  KEY `idx_lcl_conv_time` (`conversation_id`,`created_at`),
  KEY `ix_llm_call_logs_workflow_run_id` (`workflow_run_id`),
  KEY `ix_llm_call_logs_agent_id` (`agent_id`),
  KEY `idx_lcl_workflow` (`workflow_id`,`workflow_run_id`),
  KEY `ix_llm_call_logs_user_id` (`user_id`),
  KEY `idx_lcl_trace` (`trace_id`,`call_index`),
  KEY `ix_llm_call_logs_id` (`id`),
  KEY `idx_lcl_status_time` (`status`,`created_at`),
  KEY `ix_llm_call_logs_workflow_id` (`workflow_id`),
  KEY `ix_llm_call_logs_conversation_id` (`conversation_id`),
  KEY `ix_llm_call_logs_parent_call_id` (`parent_call_id`),
  KEY `ix_llm_call_logs_trace_id` (`trace_id`),
  CONSTRAINT `llm_call_logs_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `llm_call_logs_ibfk_10` FOREIGN KEY (`model_config_id`) REFERENCES `model_configs` (`id`),
  CONSTRAINT `llm_call_logs_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `llm_call_logs_ibfk_3` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`),
  CONSTRAINT `llm_call_logs_ibfk_4` FOREIGN KEY (`message_id`) REFERENCES `messages` (`id`),
  CONSTRAINT `llm_call_logs_ibfk_5` FOREIGN KEY (`agent_id`) REFERENCES `agents` (`id`),
  CONSTRAINT `llm_call_logs_ibfk_6` FOREIGN KEY (`team_id`) REFERENCES `agent_teams` (`id`),
  CONSTRAINT `llm_call_logs_ibfk_7` FOREIGN KEY (`workflow_id`) REFERENCES `workflows` (`id`),
  CONSTRAINT `llm_call_logs_ibfk_8` FOREIGN KEY (`workflow_run_id`) REFERENCES `workflow_runs` (`id`),
  CONSTRAINT `llm_call_logs_ibfk_9` FOREIGN KEY (`image_id`) REFERENCES `generated_images` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=3253 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='LLM调用日志表(可观测性)';

-- Table: mcp_servers
DROP TABLE IF EXISTS `mcp_servers`;
CREATE TABLE `mcp_servers` (
  `id` int NOT NULL AUTO_INCREMENT,
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `name` varchar(100) DEFAULT NULL COMMENT '服务器名称',
  `url` varchar(500) DEFAULT NULL COMMENT '服务器URL',
  `auth_token` varchar(500) DEFAULT NULL COMMENT '认证Token(加密)',
  `status` varchar(20) DEFAULT NULL COMMENT '状态(connected/disconnected/error)',
  `capabilities` json DEFAULT NULL COMMENT '服务器能力',
  `config` json DEFAULT NULL COMMENT '额外配置',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_mcp_tenant_name` (`tenant_id`,`name`),
  KEY `ix_mcp_servers_tenant_id` (`tenant_id`),
  CONSTRAINT `mcp_servers_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=89 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='MCP(Model Context Protocol)服务器配置表';

-- Table: mcp_tool_executions
DROP TABLE IF EXISTS `mcp_tool_executions`;
CREATE TABLE `mcp_tool_executions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `tool_id` int DEFAULT NULL COMMENT '工具ID',
  `server_id` int DEFAULT NULL COMMENT '服务器ID',
  `input_data` json DEFAULT NULL COMMENT '输入数据',
  `output_data` json DEFAULT NULL COMMENT '输出数据',
  `error` text COMMENT '错误信息',
  `status` varchar(20) DEFAULT NULL COMMENT '状态(pending/success/error)',
  `execution_time_ms` int DEFAULT NULL COMMENT '执行时间(毫秒)',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `tool_id` (`tool_id`),
  KEY `server_id` (`server_id`),
  KEY `idx_mcp_exec_tenant_tool` (`tenant_id`,`tool_id`),
  KEY `ix_mcp_tool_executions_tenant_id` (`tenant_id`),
  KEY `idx_mcp_exec_created` (`created_at`),
  CONSTRAINT `mcp_tool_executions_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `mcp_tool_executions_ibfk_2` FOREIGN KEY (`tool_id`) REFERENCES `mcp_tools` (`id`),
  CONSTRAINT `mcp_tool_executions_ibfk_3` FOREIGN KEY (`server_id`) REFERENCES `mcp_servers` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=33 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='MCP工具执行日志表';

-- Table: mcp_tools
DROP TABLE IF EXISTS `mcp_tools`;
CREATE TABLE `mcp_tools` (
  `id` int NOT NULL AUTO_INCREMENT,
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `server_id` int DEFAULT NULL COMMENT '所属服务器ID',
  `name` varchar(100) DEFAULT NULL COMMENT '工具名称',
  `description` text COMMENT '工具描述',
  `input_schema` json DEFAULT NULL COMMENT '输入参数JSON Schema',
  `output_schema` json DEFAULT NULL COMMENT '输出参数JSON Schema',
  `is_enabled` int DEFAULT NULL COMMENT '是否启用(1=启用,0=禁用)',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_mcp_tool_name` (`tenant_id`,`name`),
  KEY `server_id` (`server_id`),
  KEY `ix_mcp_tools_tenant_id` (`tenant_id`),
  KEY `idx_mcp_tool_tenant_server` (`tenant_id`,`server_id`),
  CONSTRAINT `mcp_tools_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `mcp_tools_ibfk_2` FOREIGN KEY (`server_id`) REFERENCES `mcp_servers` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=367 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='MCP工具定义表';

-- Table: messages
DROP TABLE IF EXISTS `messages`;
CREATE TABLE `messages` (
  `conversation_id` int DEFAULT NULL COMMENT '所属会话ID',
  `role` varchar(20) DEFAULT NULL COMMENT '消息角色(user/assistant/system)',
  `content` text COMMENT '消息内容',
  `msg_metadata` text COMMENT '消息元数据(JSON字符串)',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `id` int NOT NULL AUTO_INCREMENT,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `conversation_id` (`conversation_id`),
  KEY `ix_messages_id` (`id`),
  CONSTRAINT `messages_ibfk_1` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2053 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='对话消息表';

-- Table: model_configs
DROP TABLE IF EXISTS `model_configs`;
CREATE TABLE `model_configs` (
  `name` varchar(100) DEFAULT NULL COMMENT '配置名称',
  `model_type` varchar(50) DEFAULT NULL COMMENT '模型类型(ollama/openai/anthropic/zhipu/minimax)',
  `model_name` varchar(100) DEFAULT NULL COMMENT '模型名称',
  `base_url` varchar(500) DEFAULT NULL COMMENT 'API地址',
  `api_key` varchar(200) DEFAULT NULL COMMENT 'API密钥(加密)',
  `api_version` varchar(50) DEFAULT NULL COMMENT 'API版本',
  `temperature` float DEFAULT NULL COMMENT '默认温度',
  `max_tokens` int DEFAULT NULL COMMENT '最大输出Token数',
  `timeout` int DEFAULT NULL COMMENT '请求超时(秒)',
  `is_default` tinyint(1) DEFAULT NULL COMMENT '是否默认模型',
  `is_active` tinyint(1) DEFAULT NULL COMMENT '是否启用',
  `is_chat` tinyint(1) DEFAULT NULL COMMENT '可用作对话模型',
  `is_embedding` tinyint(1) DEFAULT NULL COMMENT '可用作Embedding模型',
  `is_image_generation` tinyint(1) DEFAULT NULL COMMENT '可用作图像生成模型',
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID(NULL表示全局)',
  `description` text COMMENT '模型描述',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `is_tts` tinyint(1) NOT NULL DEFAULT '0' COMMENT 'M35: Usable as a TTS (text-to-speech) model',
  `is_subtitle_generation` tinyint(1) NOT NULL DEFAULT '0' COMMENT 'M35: Usable as a subtitle generation model',
  `is_video` tinyint(1) NOT NULL DEFAULT '0' COMMENT 'M36: Usable as a video generation model (Kling/Sora/Veo future)',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_model_configs_tenant_type_name` (`tenant_id`,`model_type`,`model_name`),
  KEY `ix_model_configs_id` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1615 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI模型配置表';

-- Table: multimodal_embedding_configs
DROP TABLE IF EXISTS `multimodal_embedding_configs`;
CREATE TABLE `multimodal_embedding_configs` (
  `name` varchar(100) NOT NULL,
  `description` text,
  `provider` varchar(50) NOT NULL,
  `model_name` varchar(100) NOT NULL COMMENT 'HuggingFace id or cloud model name',
  `config` json DEFAULT NULL,
  `dimension` int DEFAULT NULL COMMENT 'Vector dim; NULL until first successful embed',
  `base_url` varchar(500) DEFAULT NULL,
  `api_key` varchar(200) DEFAULT NULL,
  `enabled` tinyint(1) NOT NULL,
  `is_default` tinyint(1) NOT NULL,
  `tenant_id` int DEFAULT NULL COMMENT 'NULL = global builtin',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_mec_tenant_name` (`tenant_id`,`name`),
  KEY `ix_multimodal_embedding_configs_id` (`id`),
  KEY `ix_multimodal_embedding_configs_provider` (`provider`),
  KEY `ix_mec_provider_enabled` (`provider`,`enabled`),
  KEY `ix_multimodal_embedding_configs_tenant_id` (`tenant_id`),
  KEY `ix_multimodal_embedding_configs_is_default` (`is_default`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table: nlp_annotation
DROP TABLE IF EXISTS `nlp_annotation`;
CREATE TABLE `nlp_annotation` (
  `content` text COMMENT '标注内容',
  `classification_id` int DEFAULT NULL COMMENT '所属分类ID',
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `classification_id` (`classification_id`),
  KEY `ix_nlp_annotation_id` (`id`),
  KEY `ix_nlp_annotation_tenant_id` (`tenant_id`),
  CONSTRAINT `nlp_annotation_ibfk_1` FOREIGN KEY (`classification_id`) REFERENCES `nlp_classification` (`id`),
  CONSTRAINT `nlp_annotation_ibfk_2` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='NLP标注数据表';

-- Table: nlp_classification
DROP TABLE IF EXISTS `nlp_classification`;
CREATE TABLE `nlp_classification` (
  `name` varchar(100) DEFAULT NULL COMMENT '分类名称',
  `description` text COMMENT '分类描述',
  `keywords` json DEFAULT NULL COMMENT '关键词列表',
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_nlp_classification_id` (`id`),
  KEY `ix_nlp_classification_tenant_id` (`tenant_id`),
  CONSTRAINT `nlp_classification_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='NLP分类模型表';

-- Table: nlp_qa
DROP TABLE IF EXISTS `nlp_qa`;
CREATE TABLE `nlp_qa` (
  `question` text COMMENT '问题',
  `answer` text COMMENT '答案',
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_nlp_qa_tenant_id` (`tenant_id`),
  KEY `ix_nlp_qa_id` (`id`),
  CONSTRAINT `nlp_qa_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='NLP问答数据表';

-- Table: notifications
DROP TABLE IF EXISTS `notifications`;
CREATE TABLE `notifications` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int DEFAULT NULL COMMENT '通知用户ID',
  `type` varchar(32) DEFAULT NULL COMMENT '通知类型',
  `title` varchar(200) DEFAULT NULL COMMENT '通知标题',
  `body` text COMMENT '通知正文',
  `resource_type` varchar(32) DEFAULT NULL COMMENT '关联资源类型',
  `resource_id` int DEFAULT NULL COMMENT '关联资源ID',
  `metadata_json` json DEFAULT NULL COMMENT '元数据JSON',
  `read_at` datetime DEFAULT NULL COMMENT '阅读时间',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_notifications_user_unread_created` (`user_id`,`read_at`,`created_at`),
  KEY `ix_notifications_user_id` (`user_id`),
  CONSTRAINT `notifications_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1073 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='站内通知表';

-- Table: operation_logs
DROP TABLE IF EXISTS `operation_logs`;
CREATE TABLE `operation_logs` (
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `module` varchar(50) DEFAULT NULL COMMENT '模块',
  `action` varchar(50) DEFAULT NULL COMMENT '动作',
  `operator` varchar(100) DEFAULT NULL COMMENT '操作者',
  `target` varchar(200) DEFAULT NULL COMMENT '操作对象',
  `method` varchar(20) DEFAULT NULL COMMENT 'HTTP方法',
  `path` varchar(500) DEFAULT NULL COMMENT '请求路径',
  `request_data` json DEFAULT NULL COMMENT '请求数据',
  `response_data` json DEFAULT NULL COMMENT '响应数据',
  `status_code` int DEFAULT NULL COMMENT 'HTTP状态码',
  `duration_ms` int DEFAULT NULL COMMENT '耗时(毫秒)',
  `level` varchar(20) DEFAULT NULL COMMENT '日志级别',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_oplog_tenant_time` (`tenant_id`,`created_at`),
  KEY `ix_operation_logs_tenant_id` (`tenant_id`),
  KEY `idx_oplog_module` (`module`,`created_at`),
  KEY `ix_operation_logs_id` (`id`),
  CONSTRAINT `operation_logs_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='操作日志表';

-- Table: permissions
DROP TABLE IF EXISTS `permissions`;
CREATE TABLE `permissions` (
  `name` varchar(50) DEFAULT NULL COMMENT '权限名称(唯一)',
  `resource` varchar(50) DEFAULT NULL COMMENT '资源类型(如knowledge/workflow/user)',
  `action` varchar(50) DEFAULT NULL COMMENT '操作类型(如create/read/update/delete)',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`),
  KEY `ix_permissions_id` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='权限定义表';

-- Table: playbooks
DROP TABLE IF EXISTS `playbooks`;
CREATE TABLE `playbooks` (
  `tenant_id` int NOT NULL,
  `name` varchar(100) NOT NULL,
  `description` text,
  `yaml_content` text NOT NULL,
  `style_tokens` json DEFAULT NULL,
  `scope` json DEFAULT NULL,
  `is_builtin` tinyint(1) NOT NULL,
  `created_by` int DEFAULT NULL,
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_playbook_tenant_name` (`tenant_id`,`name`),
  KEY `created_by` (`created_by`),
  KEY `ix_playbooks_tenant_id` (`tenant_id`),
  KEY `ix_playbooks_id` (`id`),
  KEY `ix_playbooks_name` (`name`),
  CONSTRAINT `playbooks_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `playbooks_ibfk_2` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=325 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table: ppt_tasks
DROP TABLE IF EXISTS `ppt_tasks`;
CREATE TABLE `ppt_tasks` (
  `task_id` varchar(64) NOT NULL,
  `tenant_id` int NOT NULL,
  `user_id` int NOT NULL,
  `conversation_id` int DEFAULT NULL,
  `title` varchar(255) NOT NULL,
  `status` enum('pending','processing','completed','failed') NOT NULL,
  `mode` enum('frontend','backend') NOT NULL,
  `style` varchar(32) NOT NULL,
  `include_charts` int NOT NULL,
  `file_url` varchar(512) DEFAULT NULL,
  `error` text,
  `schema_json` text,
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_ppt_tasks_task_id` (`task_id`),
  KEY `ix_ppt_tasks_tenant_status` (`tenant_id`,`status`),
  KEY `ix_ppt_tasks_tenant_id` (`tenant_id`),
  KEY `ix_ppt_tasks_user_id` (`user_id`),
  KEY `ix_ppt_tasks_id` (`id`),
  KEY `ix_ppt_tasks_user_created` (`user_id`,`created_at`),
  KEY `ix_ppt_tasks_conversation_id` (`conversation_id`),
  CONSTRAINT `ppt_tasks_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `ppt_tasks_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `ppt_tasks_ibfk_3` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=35 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table: query_logs
DROP TABLE IF EXISTS `query_logs`;
CREATE TABLE `query_logs` (
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `query_type` varchar(50) DEFAULT NULL COMMENT '查询类型',
  `table_name` varchar(100) DEFAULT NULL COMMENT '表名',
  `query_sql` text COMMENT 'SQL语句(脱敏)',
  `query_params` json DEFAULT NULL COMMENT '查询参数',
  `duration_ms` int DEFAULT NULL COMMENT '查询耗时(毫秒)',
  `row_count` int DEFAULT NULL COMMENT '返回行数',
  `cache_hit` int DEFAULT NULL COMMENT '是否命中缓存(0/1)',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_query_logs_tenant_id` (`tenant_id`),
  KEY `ix_query_logs_id` (`id`),
  KEY `idx_querylog_type` (`query_type`,`created_at`),
  KEY `idx_querylog_tenant_time` (`tenant_id`,`created_at`),
  CONSTRAINT `query_logs_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='查询日志表';

-- Table: role_permissions
DROP TABLE IF EXISTS `role_permissions`;
CREATE TABLE `role_permissions` (
  `role_id` int NOT NULL COMMENT '角色ID',
  `permission_id` int NOT NULL COMMENT '权限ID',
  PRIMARY KEY (`role_id`,`permission_id`),
  KEY `permission_id` (`permission_id`),
  CONSTRAINT `role_permissions_ibfk_1` FOREIGN KEY (`role_id`) REFERENCES `roles` (`id`),
  CONSTRAINT `role_permissions_ibfk_2` FOREIGN KEY (`permission_id`) REFERENCES `permissions` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='角色权限多对多关联表';

-- Table: roles
DROP TABLE IF EXISTS `roles`;
CREATE TABLE `roles` (
  `name` varchar(50) DEFAULT NULL COMMENT '角色名称(唯一)',
  `description` varchar(200) DEFAULT NULL COMMENT '角色描述',
  `is_active` tinyint(1) DEFAULT NULL COMMENT '是否启用',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`),
  KEY `ix_roles_id` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='角色表';

-- Table: security_settings
DROP TABLE IF EXISTS `security_settings`;
CREATE TABLE `security_settings` (
  `id` int NOT NULL AUTO_INCREMENT,
  `enforce_password_complexity` tinyint(1) DEFAULT NULL COMMENT '是否强制密码复杂度',
  `min_password_length` int DEFAULT NULL COMMENT '最小密码长度',
  `login_fail_lock_count` int DEFAULT NULL COMMENT '登录失败锁定次数',
  `token_expire_minutes` int DEFAULT NULL COMMENT 'Token过期时间(分钟)',
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  PRIMARY KEY (`id`),
  KEY `ix_security_settings_tenant_id` (`tenant_id`),
  KEY `ix_security_settings_id` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='安全设置表(每租户密码策略)';

-- Table: skill_marketplace
DROP TABLE IF EXISTS `skill_marketplace`;
CREATE TABLE `skill_marketplace` (
  `name` varchar(100) DEFAULT NULL COMMENT '技能名称',
  `category` varchar(50) DEFAULT NULL COMMENT '分类(code/writing/data/testing/design)',
  `type` varchar(20) NOT NULL DEFAULT 'prompt',
  `description` text COMMENT '技能描述',
  `content` mediumtext,
  `type_config` json DEFAULT NULL COMMENT '类型特定配置',
  `version` varchar(20) DEFAULT NULL COMMENT '版本',
  `provider` varchar(100) DEFAULT NULL COMMENT '发布者',
  `downloads` int DEFAULT NULL COMMENT '下载安装次数',
  `rating` varchar(10) DEFAULT NULL COMMENT '评分(如4.8)',
  `meta_data` json DEFAULT NULL COMMENT '元数据(如标签)',
  `is_verified` int DEFAULT NULL COMMENT '是否已认证(1=是,0=否)',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `id` int NOT NULL AUTO_INCREMENT,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_skill_marketplace_category` (`category`),
  KEY `ix_skill_marketplace_type` (`type`),
  KEY `ix_skill_marketplace_id` (`id`),
  KEY `idx_marketplace_category` (`category`)
) ENGINE=InnoDB AUTO_INCREMENT=3805 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='技能市场目录表(可安装技能列表)';

-- Table: skills
DROP TABLE IF EXISTS `skills`;
CREATE TABLE `skills` (
  `name` varchar(100) DEFAULT NULL COMMENT '技能名称(唯一)',
  `description` text COMMENT '技能描述',
  `category` varchar(50) DEFAULT NULL COMMENT '技能分类(web/data/code/chat)',
  `content` text COMMENT '技能内容(提示词或脚本)',
  `is_builtin` tinyint(1) DEFAULT NULL COMMENT '是否内置技能',
  `is_active` tinyint(1) DEFAULT NULL COMMENT '是否启用',
  `version` varchar(20) DEFAULT NULL COMMENT '版本号',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `id` int NOT NULL AUTO_INCREMENT,
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID(NULL=内置技能)',
  `type` varchar(20) DEFAULT NULL COMMENT '技能类型(prompt/script)',
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`),
  KEY `ix_skills_id` (`id`),
  KEY `ix_skills_tenant_id` (`tenant_id`)
) ENGINE=InnoDB AUTO_INCREMENT=638 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI技能表';

-- Table: stock_assets
DROP TABLE IF EXISTS `stock_assets`;
CREATE TABLE `stock_assets` (
  `name` varchar(120) NOT NULL COMMENT 'Human-readable label, e.g. ''金色日落山景''',
  `category` varchar(40) NOT NULL COMMENT '风景 / 抽象 / 商务 / 人物 / 产品',
  `tags` json DEFAULT NULL COMMENT 'Free-form tag list, e.g. [''sunset'', ''mountain'']',
  `file_path` varchar(500) NOT NULL COMMENT 'Relative to settings.STORAGE_DIR, e.g. ''stock/landscape/sunset-01.png''',
  `mime_type` varchar(50) NOT NULL,
  `file_size` int NOT NULL,
  `width` int DEFAULT NULL,
  `height` int DEFAULT NULL,
  `source` varchar(20) NOT NULL COMMENT 'builtin | pexels | uploaded',
  `pexels_id` int DEFAULT NULL,
  `tenant_id` int DEFAULT NULL COMMENT 'NULL = global builtin',
  `description` text,
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_stock_assets_tenant_id` (`tenant_id`),
  KEY `ix_stock_assets_category_created` (`category`,`created_at`),
  KEY `ix_stock_assets_id` (`id`),
  KEY `ix_stock_assets_category` (`category`)
) ENGINE=InnoDB AUTO_INCREMENT=768 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table: stock_musics
DROP TABLE IF EXISTS `stock_musics`;
CREATE TABLE `stock_musics` (
  `name` varchar(120) NOT NULL COMMENT 'Human-readable label, e.g. ''Mellow Piano''',
  `category` varchar(40) NOT NULL COMMENT '舒缓 / 振奋 / 戏剧 / 商务 / 氛围',
  `description` text,
  `file_path` varchar(500) NOT NULL,
  `mime_type` varchar(50) NOT NULL,
  `file_size` int NOT NULL,
  `duration_seconds` float NOT NULL COMMENT 'Track length in seconds',
  `source` varchar(20) NOT NULL COMMENT 'builtin | uploaded',
  `tenant_id` int DEFAULT NULL COMMENT 'NULL = global builtin',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_stock_musics_tenant_id` (`tenant_id`),
  KEY `ix_stock_musics_id` (`id`),
  KEY `ix_stock_musics_category_created` (`category`,`created_at`),
  KEY `ix_stock_musics_category` (`category`)
) ENGINE=InnoDB AUTO_INCREMENT=390 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table: subtitles
DROP TABLE IF EXISTS `subtitles`;
CREATE TABLE `subtitles` (
  `tenant_id` int NOT NULL,
  `user_id` int NOT NULL,
  `tts_job_id` int DEFAULT NULL,
  `source_type` varchar(20) NOT NULL,
  `language` varchar(10) NOT NULL,
  `format` varchar(10) NOT NULL,
  `content` text NOT NULL,
  `cue_count` int NOT NULL,
  `duration_ms` int NOT NULL,
  `char_count` int NOT NULL,
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_subtitles_id` (`id`),
  KEY `ix_subtitles_tenant_id` (`tenant_id`),
  KEY `ix_subtitles_tts_job_id` (`tts_job_id`),
  KEY `ix_subtitles_tenant_created` (`tenant_id`,`created_at`),
  KEY `ix_subtitles_user_id` (`user_id`),
  CONSTRAINT `subtitles_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `subtitles_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `subtitles_ibfk_3` FOREIGN KEY (`tts_job_id`) REFERENCES `generated_audios` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=220 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table: system_configs
DROP TABLE IF EXISTS `system_configs`;
CREATE TABLE `system_configs` (
  `key` varchar(100) DEFAULT NULL COMMENT '配置键(唯一,点分隔)',
  `value` json DEFAULT NULL COMMENT '配置值(JSON格式)',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_system_configs_key` (`key`),
  KEY `ix_system_configs_id` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='系统配置表(平台级键值对)';

-- Table: system_settings
DROP TABLE IF EXISTS `system_settings`;
CREATE TABLE `system_settings` (
  `id` int NOT NULL AUTO_INCREMENT,
  `system_name` varchar(100) DEFAULT NULL COMMENT '系统名称',
  `system_description` text COMMENT '系统描述',
  `default_model` int DEFAULT NULL COMMENT '默认模型ID',
  `embedding_model` int DEFAULT NULL COMMENT '默认Embedding模型ID',
  `chat_history_days` int DEFAULT NULL COMMENT '聊天历史保留天数',
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  PRIMARY KEY (`id`),
  KEY `ix_system_settings_tenant_id` (`tenant_id`),
  KEY `ix_system_settings_id` (`id`),
  KEY `fk_system_settings_default_model` (`default_model`),
  KEY `fk_system_settings_embedding_model` (`embedding_model`),
  CONSTRAINT `fk_system_settings_default_model` FOREIGN KEY (`default_model`) REFERENCES `model_configs` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `fk_system_settings_embedding_model` FOREIGN KEY (`embedding_model`) REFERENCES `model_configs` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='系统设置表(每租户)';

-- Table: tenants
DROP TABLE IF EXISTS `tenants`;
CREATE TABLE `tenants` (
  `name` varchar(100) DEFAULT NULL COMMENT '租户名称',
  `code` varchar(50) DEFAULT NULL COMMENT '租户代码(唯一)',
  `status` tinyint(1) DEFAULT NULL COMMENT '租户状态(1=启用,0=禁用)',
  `max_users` int DEFAULT NULL COMMENT '最大用户数限制',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_tenants_code` (`code`),
  KEY `ix_tenants_id` (`id`),
  KEY `ix_tenants_name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=7630 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='租户表';

-- Table: text2sql_data_sources
DROP TABLE IF EXISTS `text2sql_data_sources`;
CREATE TABLE `text2sql_data_sources` (
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `name` varchar(100) DEFAULT NULL COMMENT '数据源名称',
  `db_name` varchar(64) DEFAULT NULL COMMENT '数据库名称',
  `table_allowlist` json DEFAULT NULL COMMENT '允许的表名列表',
  `field_allowlist` json DEFAULT NULL COMMENT '允许的字段列表{表名:[字段]}',
  `max_rows` int DEFAULT NULL COMMENT '最大返回行数',
  `timeout_ms` int DEFAULT NULL COMMENT '查询超时(毫秒)',
  `description` text COMMENT '数据源描述',
  `is_active` int DEFAULT NULL COMMENT '是否启用(1=是,0=否)',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_text2sql_data_sources_id` (`id`),
  KEY `ix_text2sql_ds_tenant_active` (`tenant_id`,`is_active`),
  KEY `ix_text2sql_data_sources_tenant_id` (`tenant_id`),
  CONSTRAINT `text2sql_data_sources_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=120 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Text2SQL数据源配置表';

-- Table: text2sql_queries
DROP TABLE IF EXISTS `text2sql_queries`;
CREATE TABLE `text2sql_queries` (
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `user_id` int DEFAULT NULL COMMENT '用户ID',
  `data_source_id` int DEFAULT NULL COMMENT '数据源ID',
  `question` text COMMENT '用户问题',
  `generated_sql` text COMMENT '生成的SQL',
  `attempts` int DEFAULT NULL COMMENT '尝试次数',
  `status` varchar(20) DEFAULT NULL COMMENT '状态(pending/generating/executing/explaining/success/rejected/failed)',
  `error_type` varchar(40) DEFAULT NULL COMMENT '错误类型',
  `error_message` text COMMENT '错误信息',
  `rows_json` json DEFAULT NULL COMMENT '结果行(JSON)',
  `columns_json` json DEFAULT NULL COMMENT '结果列(JSON)',
  `row_count` int DEFAULT NULL COMMENT '结果行数',
  `truncated` int DEFAULT NULL COMMENT '是否被截断(0/1)',
  `explanation` text COMMENT '中文解释',
  `confidence` int DEFAULT NULL COMMENT '置信度(0-100)',
  `duration_ms` int DEFAULT NULL COMMENT '耗时(毫秒)',
  `generate_call_id` varchar(36) DEFAULT NULL COMMENT 'SQL生成调用ID',
  `explain_call_id` varchar(36) DEFAULT NULL COMMENT '解释生成调用ID',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_text2sql_queries_id` (`id`),
  KEY `ix_text2sql_queries_user_id` (`user_id`),
  KEY `ix_text2sql_queries_tenant_status_created` (`tenant_id`,`status`,`created_at`),
  KEY `ix_text2sql_queries_generate_call_id` (`generate_call_id`),
  KEY `ix_text2sql_queries_data_source_created` (`data_source_id`,`created_at`),
  KEY `ix_text2sql_queries_tenant_id` (`tenant_id`),
  KEY `ix_text2sql_queries_data_source_id` (`data_source_id`),
  CONSTRAINT `text2sql_queries_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `text2sql_queries_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `text2sql_queries_ibfk_3` FOREIGN KEY (`data_source_id`) REFERENCES `text2sql_data_sources` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB AUTO_INCREMENT=297 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Text2SQL查询记录表';

-- Table: users
DROP TABLE IF EXISTS `users`;
CREATE TABLE `users` (
  `username` varchar(50) DEFAULT NULL COMMENT '用户名(唯一)',
  `email` varchar(100) DEFAULT NULL COMMENT '邮箱(唯一)',
  `hashed_password` varchar(255) DEFAULT NULL COMMENT '加密密码',
  `full_name` varchar(100) DEFAULT NULL COMMENT '姓名',
  `is_active` tinyint(1) DEFAULT NULL COMMENT '是否激活(1=激活,0=禁用)',
  `is_superuser` tinyint(1) DEFAULT NULL COMMENT '是否超级管理员',
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_users_email` (`email`),
  UNIQUE KEY `ix_users_username` (`username`),
  KEY `ix_users_id` (`id`),
  KEY `ix_users_tenant_id` (`tenant_id`),
  CONSTRAINT `users_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=11655 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户表';

-- Table: vision_classification
DROP TABLE IF EXISTS `vision_classification`;
CREATE TABLE `vision_classification` (
  `name` varchar(100) DEFAULT NULL COMMENT '分类名称',
  `description` varchar(500) DEFAULT NULL COMMENT '分类描述',
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_vision_classification_tenant_id` (`tenant_id`),
  KEY `ix_vision_classification_id` (`id`),
  CONSTRAINT `vision_classification_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='视觉分类模型表';

-- Table: vision_image
DROP TABLE IF EXISTS `vision_image`;
CREATE TABLE `vision_image` (
  `filename` varchar(255) DEFAULT NULL COMMENT '文件名',
  `file_path` varchar(500) DEFAULT NULL COMMENT '文件路径',
  `classification_id` int DEFAULT NULL COMMENT '所属分类ID',
  `features` json DEFAULT NULL COMMENT '特征向量',
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_vision_image_classification_id` (`classification_id`),
  KEY `ix_vision_image_tenant_id` (`tenant_id`),
  KEY `ix_vision_image_id` (`id`),
  CONSTRAINT `vision_image_ibfk_1` FOREIGN KEY (`classification_id`) REFERENCES `vision_classification` (`id`),
  CONSTRAINT `vision_image_ibfk_2` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='视觉图像表';

-- Table: workflow_node_runs
DROP TABLE IF EXISTS `workflow_node_runs`;
CREATE TABLE `workflow_node_runs` (
  `run_id` int DEFAULT NULL COMMENT '工作流运行ID',
  `node_id` varchar(100) DEFAULT NULL COMMENT '节点ID(DAG定义中的ID)',
  `node_type` varchar(50) DEFAULT NULL COMMENT '节点类型(input/agent/condition/parallel/output)',
  `status` varchar(20) DEFAULT NULL COMMENT '状态(pending/running/completed/failed/skipped)',
  `input_data` json DEFAULT NULL COMMENT '输入数据',
  `output_data` json DEFAULT NULL COMMENT '输出数据',
  `error_message` text COMMENT '错误信息',
  `started_at` datetime DEFAULT NULL COMMENT '开始时间',
  `finished_at` datetime DEFAULT NULL COMMENT '结束时间',
  `execution_order` int DEFAULT NULL COMMENT '执行顺序',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_node_run_run_node` (`run_id`,`node_id`),
  KEY `ix_workflow_node_runs_id` (`id`),
  KEY `ix_workflow_node_runs_run_id` (`run_id`),
  CONSTRAINT `workflow_node_runs_ibfk_1` FOREIGN KEY (`run_id`) REFERENCES `workflow_runs` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=707 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='工作流节点执行记录表';

-- Table: workflow_runs
DROP TABLE IF EXISTS `workflow_runs`;
CREATE TABLE `workflow_runs` (
  `workflow_id` int DEFAULT NULL COMMENT '工作流ID',
  `status` varchar(20) DEFAULT NULL COMMENT '状态(pending/running/completed/failed/cancelled)',
  `trigger_source` varchar(20) DEFAULT NULL COMMENT '触发来源(manual/scheduled)',
  `input_data` json DEFAULT NULL COMMENT '输入数据',
  `output_data` json DEFAULT NULL COMMENT '输出数据',
  `error_message` text COMMENT '错误信息',
  `started_at` datetime DEFAULT NULL COMMENT '开始时间',
  `finished_at` datetime DEFAULT NULL COMMENT '结束时间',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_workflow_runs_workflow_id` (`workflow_id`),
  KEY `ix_workflow_runs_id` (`id`),
  KEY `idx_workflow_run_workflow_started` (`workflow_id`,`started_at` DESC),
  KEY `idx_workflow_run_workflow_status` (`workflow_id`,`status`),
  CONSTRAINT `workflow_runs_ibfk_1` FOREIGN KEY (`workflow_id`) REFERENCES `workflows` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=529 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='工作流运行记录表';

-- Table: workflow_schedules
DROP TABLE IF EXISTS `workflow_schedules`;
CREATE TABLE `workflow_schedules` (
  `workflow_id` int DEFAULT NULL COMMENT '工作流ID',
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `name` varchar(100) DEFAULT NULL COMMENT '调度名称',
  `cron_expression` varchar(100) DEFAULT NULL COMMENT 'Cron表达式',
  `input_data` json DEFAULT NULL COMMENT '固定输入数据',
  `is_active` tinyint(1) DEFAULT NULL COMMENT '是否启用',
  `last_run_at` datetime DEFAULT NULL COMMENT '上次运行时间',
  `next_run_at` datetime DEFAULT NULL COMMENT '下次运行时间',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_workflow_schedules_id` (`id`),
  KEY `idx_schedule_workflow_active` (`workflow_id`,`is_active`),
  KEY `ix_workflow_schedules_tenant_id` (`tenant_id`),
  KEY `ix_workflow_schedules_workflow_id` (`workflow_id`),
  CONSTRAINT `workflow_schedules_ibfk_1` FOREIGN KEY (`workflow_id`) REFERENCES `workflows` (`id`),
  CONSTRAINT `workflow_schedules_ibfk_2` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='工作流定时调度配置表';

-- Table: workflow_templates
DROP TABLE IF EXISTS `workflow_templates`;
CREATE TABLE `workflow_templates` (
  `name` varchar(100) DEFAULT NULL COMMENT '模板名称',
  `description` text COMMENT '模板描述',
  `category` varchar(50) DEFAULT NULL COMMENT '分类',
  `tags` json DEFAULT NULL COMMENT '标签列表',
  `workflow_json` json DEFAULT NULL COMMENT '工作流定义JSON',
  `author_id` int DEFAULT NULL COMMENT '作者用户ID',
  `author_name` varchar(100) DEFAULT NULL COMMENT '作者名称',
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID(可选)',
  `downloads` int DEFAULT NULL COMMENT '下载次数',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_workflow_templates_category` (`category`),
  KEY `ix_workflow_templates_author_id` (`author_id`),
  KEY `ix_workflow_templates_tenant_id` (`tenant_id`),
  KEY `idx_wftemplate_category` (`category`),
  KEY `ix_workflow_templates_id` (`id`),
  CONSTRAINT `workflow_templates_ibfk_1` FOREIGN KEY (`author_id`) REFERENCES `users` (`id`),
  CONSTRAINT `workflow_templates_ibfk_2` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=9 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='工作流模板表(公开可导入)';

-- Table: workflows
DROP TABLE IF EXISTS `workflows`;
CREATE TABLE `workflows` (
  `name` varchar(100) DEFAULT NULL COMMENT '工作流名称',
  `description` text COMMENT '工作流描述',
  `definition` json DEFAULT NULL COMMENT 'DAG图定义(JSON)',
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `is_active` tinyint(1) DEFAULT NULL COMMENT '是否启用',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_workflows_tenant_id` (`tenant_id`),
  KEY `ix_workflows_id` (`id`),
  KEY `idx_workflow_tenant_active_created` (`tenant_id`,`is_active`,`created_at` DESC),
  CONSTRAINT `workflows_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1277 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='工作流定义表';

-- Table: workspace_member_permissions
DROP TABLE IF EXISTS `workspace_member_permissions`;
CREATE TABLE `workspace_member_permissions` (
  `workspace_id` int NOT NULL COMMENT 'FK -> workspaces.id; ON DELETE CASCADE drops the grants with the workspace',
  `user_id` int NOT NULL COMMENT 'FK -> users.id; ON DELETE CASCADE drops the grants when the user is hard-deleted',
  `permission` varchar(64) NOT NULL COMMENT 'ACL permission token (e.g. ''kb.read'', ''document.create''); see permission_service._PERM_IMPLIES',
  `granted_by` int DEFAULT NULL COMMENT 'Who granted the permission (audit trail); nullable + SET NULL so deleting a user does not cascade',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_wmp_ws_user_perm` (`workspace_id`,`user_id`,`permission`),
  KEY `granted_by` (`granted_by`),
  KEY `idx_wmp_user` (`user_id`),
  KEY `idx_wmp_ws` (`workspace_id`),
  KEY `ix_workspace_member_permissions_id` (`id`),
  CONSTRAINT `workspace_member_permissions_ibfk_1` FOREIGN KEY (`workspace_id`) REFERENCES `workspaces` (`id`) ON DELETE CASCADE,
  CONSTRAINT `workspace_member_permissions_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `workspace_member_permissions_ibfk_3` FOREIGN KEY (`granted_by`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table: workspaces
DROP TABLE IF EXISTS `workspaces`;
CREATE TABLE `workspaces` (
  `tenant_id` int NOT NULL,
  `name` varchar(100) NOT NULL,
  `description` text,
  `owner_id` int DEFAULT NULL,
  `icon` varchar(50) DEFAULT NULL,
  `color` varchar(20) DEFAULT NULL,
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_workspaces_tenant_name` (`tenant_id`,`name`),
  KEY `owner_id` (`owner_id`),
  KEY `ix_workspaces_id` (`id`),
  KEY `idx_workspaces_tenant` (`tenant_id`),
  CONSTRAINT `workspaces_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE,
  CONSTRAINT `workspaces_ibfk_2` FOREIGN KEY (`owner_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table: wx_accounts
DROP TABLE IF EXISTS `wx_accounts`;
CREATE TABLE `wx_accounts` (
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `user_id` int DEFAULT NULL COMMENT '管理员用户ID',
  `app_id` varchar(50) DEFAULT NULL COMMENT 'AppID',
  `app_secret_encrypted` varbinary(512) DEFAULT NULL COMMENT 'AppSecret(加密)',
  `name` varchar(100) DEFAULT NULL COMMENT '账号名称',
  `account_type` varchar(20) DEFAULT NULL COMMENT '账号类型(subscription/service)',
  `is_mock` tinyint(1) DEFAULT NULL COMMENT '是否模拟模式',
  `access_token` varchar(512) DEFAULT NULL COMMENT '调用凭证',
  `access_token_expires_at` datetime DEFAULT NULL COMMENT 'Token过期时间',
  `ip_whitelist` text COMMENT 'IP白名单',
  `last_verified_at` datetime DEFAULT NULL COMMENT '最后验证时间',
  `is_active` tinyint(1) DEFAULT NULL COMMENT '是否启用',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_wx_accounts_tenant_appid` (`tenant_id`,`app_id`),
  KEY `idx_wx_accounts_tenant_active` (`tenant_id`,`is_active`),
  KEY `ix_wx_accounts_tenant_id` (`tenant_id`),
  KEY `ix_wx_accounts_id` (`id`),
  KEY `ix_wx_accounts_user_id` (`user_id`),
  CONSTRAINT `wx_accounts_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `wx_accounts_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=823 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='微信公众号账号表';

-- Table: wx_draft_sections
DROP TABLE IF EXISTS `wx_draft_sections`;
CREATE TABLE `wx_draft_sections` (
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `draft_id` int DEFAULT NULL COMMENT '所属草稿ID',
  `order_index` int DEFAULT NULL COMMENT '章节排序',
  `heading` varchar(200) DEFAULT NULL COMMENT '章节标题',
  `content_markdown` longtext COMMENT 'Markdown内容',
  `content_html` longtext COMMENT 'HTML内容',
  `ai_prompt` text COMMENT 'AI写作提示词',
  `ai_model_config_id` int DEFAULT NULL COMMENT 'AI模型配置ID',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_wx_draft_sections_draft_order` (`draft_id`,`order_index`),
  KEY `ai_model_config_id` (`ai_model_config_id`),
  KEY `ix_wx_draft_sections_draft_id` (`draft_id`),
  KEY `ix_wx_draft_sections_tenant_id` (`tenant_id`),
  KEY `ix_wx_draft_sections_id` (`id`),
  CONSTRAINT `wx_draft_sections_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `wx_draft_sections_ibfk_2` FOREIGN KEY (`draft_id`) REFERENCES `wx_drafts` (`id`) ON DELETE CASCADE,
  CONSTRAINT `wx_draft_sections_ibfk_3` FOREIGN KEY (`ai_model_config_id`) REFERENCES `model_configs` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=675 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='微信草稿章节表';

-- Table: wx_drafts
DROP TABLE IF EXISTS `wx_drafts`;
CREATE TABLE `wx_drafts` (
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `user_id` int DEFAULT NULL COMMENT '创建人用户ID',
  `account_id` int DEFAULT NULL COMMENT '关联公众号ID',
  `template_id` int DEFAULT NULL COMMENT '关联模板ID',
  `title` varchar(200) DEFAULT NULL COMMENT '文章标题',
  `summary` varchar(500) DEFAULT NULL COMMENT '文章摘要',
  `author` varchar(50) DEFAULT NULL COMMENT '作者',
  `content_markdown` longtext COMMENT 'Markdown正文',
  `content_html` longtext COMMENT 'HTML正文',
  `cover_image_id` int DEFAULT NULL COMMENT '封面图生成ID',
  `cover_url` varchar(500) DEFAULT NULL COMMENT '封面图URL',
  `status` varchar(20) DEFAULT NULL COMMENT '状态(draft/published/scheduled)',
  `kb_id` int DEFAULT NULL COMMENT '关联知识库ID',
  `tags` json DEFAULT NULL COMMENT '标签列表',
  `scheduled_at` datetime DEFAULT NULL COMMENT '定时发布时间',
  `published_at` datetime DEFAULT NULL COMMENT '实际发布时间',
  `wechat_media_id` varchar(100) DEFAULT NULL COMMENT '微信素材MediaId',
  `error_message` text COMMENT '错误信息',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_wx_drafts_user_id` (`user_id`),
  KEY `ix_wx_drafts_status` (`status`),
  KEY `ix_wx_drafts_scheduled_at` (`scheduled_at`),
  KEY `ix_wx_drafts_cover_image_id` (`cover_image_id`),
  KEY `ix_wx_drafts_template_id` (`template_id`),
  KEY `idx_wx_drafts_tenant_updated` (`tenant_id`,`updated_at`),
  KEY `ix_wx_drafts_tenant_id` (`tenant_id`),
  KEY `ix_wx_drafts_account_id` (`account_id`),
  KEY `ix_wx_drafts_id` (`id`),
  KEY `ix_wx_drafts_kb_id` (`kb_id`),
  KEY `idx_wx_drafts_tenant_status` (`tenant_id`,`status`),
  CONSTRAINT `wx_drafts_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `wx_drafts_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `wx_drafts_ibfk_3` FOREIGN KEY (`account_id`) REFERENCES `wx_accounts` (`id`) ON DELETE SET NULL,
  CONSTRAINT `wx_drafts_ibfk_4` FOREIGN KEY (`template_id`) REFERENCES `wx_templates` (`id`) ON DELETE SET NULL,
  CONSTRAINT `wx_drafts_ibfk_5` FOREIGN KEY (`cover_image_id`) REFERENCES `generated_images` (`id`) ON DELETE SET NULL,
  CONSTRAINT `wx_drafts_ibfk_6` FOREIGN KEY (`kb_id`) REFERENCES `knowledge_bases` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=1151 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='微信图文草稿表';

-- Table: wx_materials
DROP TABLE IF EXISTS `wx_materials`;
CREATE TABLE `wx_materials` (
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `user_id` int DEFAULT NULL COMMENT '用户ID',
  `title` varchar(200) DEFAULT NULL COMMENT '素材标题',
  `content` longtext COMMENT '素材内容',
  `source_type` varchar(20) DEFAULT NULL COMMENT '来源类型',
  `kb_chunk_id` int DEFAULT NULL COMMENT '关联知识库分块ID',
  `tags` json DEFAULT NULL COMMENT '标签',
  `is_used` tinyint(1) DEFAULT NULL COMMENT '是否已使用',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_wx_materials_id` (`id`),
  KEY `ix_wx_materials_kb_chunk_id` (`kb_chunk_id`),
  KEY `ix_wx_materials_source_type` (`source_type`),
  KEY `ix_wx_materials_tenant_id` (`tenant_id`),
  KEY `idx_wx_materials_tenant_source` (`tenant_id`,`source_type`),
  KEY `ix_wx_materials_user_id` (`user_id`),
  CONSTRAINT `wx_materials_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `wx_materials_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `wx_materials_ibfk_3` FOREIGN KEY (`kb_chunk_id`) REFERENCES `document_chunks` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=368 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='微信素材表';

-- Table: wx_publish_records
DROP TABLE IF EXISTS `wx_publish_records`;
CREATE TABLE `wx_publish_records` (
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `draft_id` int DEFAULT NULL COMMENT '草稿ID',
  `account_id` int DEFAULT NULL COMMENT '公众号ID',
  `user_id` int DEFAULT NULL COMMENT '发布人用户ID',
  `wechat_media_id` varchar(100) DEFAULT NULL COMMENT '微信MediaId',
  `wechat_msg_id` varchar(100) DEFAULT NULL COMMENT '微信消息ID',
  `status` varchar(20) DEFAULT NULL COMMENT '发布状态',
  `error_code` varchar(50) DEFAULT NULL COMMENT '错误码',
  `error_message` text COMMENT '错误信息',
  `duration_ms` int DEFAULT NULL COMMENT '耗时(毫秒)',
  `started_at` datetime DEFAULT NULL COMMENT '开始时间',
  `completed_at` datetime DEFAULT NULL COMMENT '完成时间',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `account_id` (`account_id`),
  KEY `ix_wx_publish_records_id` (`id`),
  KEY `ix_wx_publish_records_user_id` (`user_id`),
  KEY `ix_wx_publish_records_draft_id` (`draft_id`),
  KEY `ix_wx_publish_records_status` (`status`),
  KEY `ix_wx_publish_records_tenant_id` (`tenant_id`),
  CONSTRAINT `wx_publish_records_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `wx_publish_records_ibfk_2` FOREIGN KEY (`draft_id`) REFERENCES `wx_drafts` (`id`) ON DELETE CASCADE,
  CONSTRAINT `wx_publish_records_ibfk_3` FOREIGN KEY (`account_id`) REFERENCES `wx_accounts` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `wx_publish_records_ibfk_4` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=319 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='微信发布记录表';

-- Table: wx_templates
DROP TABLE IF EXISTS `wx_templates`;
CREATE TABLE `wx_templates` (
  `tenant_id` int DEFAULT NULL COMMENT '所属租户ID',
  `name` varchar(100) DEFAULT NULL COMMENT '模板名称',
  `category` varchar(50) DEFAULT NULL COMMENT '分类',
  `description` varchar(500) DEFAULT NULL COMMENT '模板描述',
  `html_body` longtext COMMENT 'HTML正文',
  `css_variables` json DEFAULT NULL COMMENT 'CSS变量配置',
  `preview_html` longtext COMMENT '预览HTML',
  `thumbnail` mediumblob COMMENT '缩略图',
  `is_system` tinyint(1) DEFAULT NULL COMMENT '是否系统模板',
  `created_by` int DEFAULT NULL COMMENT '创建人用户ID',
  `usage_count` int DEFAULT NULL COMMENT '使用次数',
  `id` int NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `created_by` (`created_by`),
  KEY `ix_wx_templates_category` (`category`),
  KEY `ix_wx_templates_id` (`id`),
  KEY `ix_wx_templates_tenant_id` (`tenant_id`),
  KEY `idx_wx_templates_tenant_category` (`tenant_id`,`category`),
  CONSTRAINT `wx_templates_ibfk_1` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
  CONSTRAINT `wx_templates_ibfk_2` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=347 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='微信图文模板表';

SET FOREIGN_KEY_CHECKS=1;
