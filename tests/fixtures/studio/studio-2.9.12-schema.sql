-- Msty Studio 2.9.12 workspace schema (msty.cloud.db), dumped from a disposable Linux install.
-- Schema only plus __drizzle_migrations rows. No user data.
CREATE TABLE "__drizzle_migrations" (
    id SERIAL PRIMARY KEY,
    hash text NOT NULL,
    created_at numeric
  );

CREATE TABLE `bookmarkedEntities` (
	`id` text PRIMARY KEY NOT NULL,
	`entity` text NOT NULL,
	`content` text NOT NULL,
	`entityId` text NOT NULL,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`extras` text
);

CREATE TABLE `conversationTextChatSplits` (
	`id` text PRIMARY KEY NOT NULL,
	`conversationId` text NOT NULL,
	`systemPrompt` text,
	`modelInfo` text,
	`attachments` text,
	`rtdInfo` text,
	`toolsetsInfo` text,
	`liveContextsInfo` text,
	`extras` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL, `personaInfo` text, `knowledgeStacksInfo` text, `crewInfo` text, `userPersonaInfo` text, `agentSessionId` text, `agentId` text, `workspacePath` text, `agentSessionSource` text, `agentSessionImportedAt` text,
	FOREIGN KEY (`conversationId`) REFERENCES `conversationTexts`(`id`) ON UPDATE no action ON DELETE cascade
);

CREATE TABLE `conversationTextMessageRealTimeData` (
	`id` text PRIMARY KEY NOT NULL,
	`provider` text NOT NULL,
	`synthesizedQuery` text,
	`sources` text,
	`extras` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE `conversationTextMessages` (
	`id` text PRIMARY KEY NOT NULL,
	`content` text,
	`forgeContent` text,
	`role` text NOT NULL,
	`chatSplitId` text NOT NULL,
	`branchParentId` text,
	`modelInfo` text,
	`attachments` text,
	`contextShieldInfo` text,
	`rtdId` text,
	`toolsetsInfo` text,
	`toolCallTokensUsageAggregate` text,
	`completionTokensUsage` text,
	`knowledgeStacksInfo` text,
	`responseMetricsInfo` text,
	`liveContextResultsIds` text,
	`extras` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL, `visibility` text, `knowledgeStackChunksId` text REFERENCES conversationTextMessageKnowledgeStackChunks (id), updatedAt TEXT,
	FOREIGN KEY (`chatSplitId`) REFERENCES `conversationTextChatSplits`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`branchParentId`) REFERENCES `conversationTextMessages`(`id`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (`rtdId`) REFERENCES `conversationTextMessageRealTimeData`(`id`) ON UPDATE no action ON DELETE set null
);

CREATE TABLE `conversationTextMessageToolCalls` (
	`id` text PRIMARY KEY NOT NULL,
	`messageId` text,
	`usage` text,
	`calls` text,
	`extras` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`messageId`) REFERENCES `conversationTextMessages`(`id`) ON UPDATE no action ON DELETE cascade
);

CREATE TABLE `conversationTextProjects` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`description` text,
	`colorIcon` text,
	`isExpanded` integer DEFAULT true NOT NULL,
	`systemPrompt` text,
	`modelInfo` text,
	`attachments` text,
	`rtdInfo` text,
	`toolsetsInfo` text,
	`liveContextsInfo` text,
	`sortOrder` integer DEFAULT -1 NOT NULL,
	`projectParentId` text,
	`extras` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`projectParentId`) REFERENCES `conversationTextProjects`(`id`) ON UPDATE no action ON DELETE set null
);

CREATE INDEX `textConversationProjectsNameIdx` ON `conversationTextProjects` (`name`);

CREATE TABLE `conversationTexts` (
	`id` text PRIMARY KEY NOT NULL,
	`title` text NOT NULL,
	`projectId` text NOT NULL,
	`type` text,
	`chatSplitsOrder` text,
	`extras` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL, `shadowPersonaSettings` text, `sourceAgentId` text, `alienConversationId` text, archivedAt TEXT, lastActivityAt TEXT,
	FOREIGN KEY (`projectId`) REFERENCES `conversationTextProjects`(`id`) ON UPDATE no action ON DELETE cascade
);

CREATE INDEX `textConversationTextsTitleIdx` ON `conversationTexts` (`title`);

CREATE TABLE `insightsLanguageModelUsage` (
	`id` text PRIMARY KEY NOT NULL,
	`providerId` text NOT NULL,
	`providerType` text NOT NULL,
	`modelId` text NOT NULL,
	`promptTokens` integer NOT NULL,
	`completionTokens` integer NOT NULL,
	`totalTokens` integer NOT NULL,
	`inputCostInUSD` real NOT NULL,
	`outputCostInUSD` real NOT NULL,
	`totalCostInUSD` real NOT NULL,
	`timeToFirstResponseInSec` real NOT NULL,
	`totalTimeInSec` real NOT NULL,
	`tokensPerSec` real NOT NULL,
	`chatSplitId` text,
	`conversationId` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`extras` text,
	FOREIGN KEY (`chatSplitId`) REFERENCES `conversationTextChatSplits`(`id`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (`conversationId`) REFERENCES `conversationTexts`(`id`) ON UPDATE no action ON DELETE set null
);

CREATE INDEX `insightsLanguageModelUsageProviderIdModelIdIdx` ON `insightsLanguageModelUsage` (`providerId`,`modelId`);

CREATE INDEX `insightsLanguageModelUsageProviderIdIdx` ON `insightsLanguageModelUsage` (`providerId`);

CREATE INDEX `insightsLanguageModelUsageConversationIdIdx` ON `insightsLanguageModelUsage` (`conversationId`);

CREATE INDEX `insightsLanguageModelUsageChatSplitIdIdx` ON `insightsLanguageModelUsage` (`chatSplitId`);

CREATE TABLE `languageModelConfigs` (
	`id` text PRIMARY KEY NOT NULL,
	`providerId` text NOT NULL,
	`modelId` text NOT NULL,
	`value` text,
	`extras` text, `logo` text,
	FOREIGN KEY (`providerId`) REFERENCES `languageModelsProviders`(`id`) ON UPDATE no action ON DELETE cascade
);

CREATE UNIQUE INDEX `languageModelConfigsProviderIdAndModelIdIdx` ON `languageModelConfigs` (`providerId`,`modelId`);

CREATE TABLE `languageModelParamsPresets` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`value` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE UNIQUE INDEX `languageModelParamsPresets_name_unique` ON `languageModelParamsPresets` (`name`);

CREATE INDEX `languageModelParamsPresetsNameIdx` ON `languageModelParamsPresets` (`name`);

CREATE TABLE `languageModelsProviders` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`providerId` text NOT NULL,
	`credentials` text,
	`models` text,
	`extras` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
, `logo` text);

CREATE INDEX `languageModelsProvidersNameIdx` ON `languageModelsProviders` (`name`);

CREATE TABLE `liveContexts` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`type` text NOT NULL,
	`prompt` text,
	`payload` text NOT NULL,
	`priority` real DEFAULT (unixepoch() * 1000) NOT NULL,
	`notes` text,
	`extras` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
, `folderId` text REFERENCES liveContextFolders(id));

CREATE UNIQUE INDEX `liveContexts_name_unique` ON `liveContexts` (`name`);

CREATE TABLE `liveContextResults` (
	`id` text PRIMARY KEY NOT NULL,
	`data` text,
	`liveContextId` text,
	`messageId` text NOT NULL,
	`isSelected` integer DEFAULT true NOT NULL,
	`extras` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`liveContextId`) REFERENCES `liveContexts`(`id`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (`messageId`) REFERENCES `conversationTextMessages`(`id`) ON UPDATE no action ON DELETE cascade
);

CREATE TABLE `modelMatchmakerStrengthPresets` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`notes` text,
	`payload` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE UNIQUE INDEX `modelMatchmakerStrengthPresets_name_unique` ON `modelMatchmakerStrengthPresets` (`name`);

CREATE INDEX `strengthPresetsNameIdx` ON `modelMatchmakerStrengthPresets` (`name`);

CREATE TABLE `settings` (
	`id` text PRIMARY KEY NOT NULL,
	`key` text NOT NULL,
	`value` text
);

CREATE UNIQUE INDEX `settings_key_unique` ON `settings` (`key`);

CREATE INDEX `settingsKeyIdx` ON `settings` (`key`);

CREATE TABLE `splitPresets` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`type` text NOT NULL,
	`templates` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE UNIQUE INDEX `splitPresets_name_unique` ON `splitPresets` (`name`);

CREATE INDEX `splitPresetsNameIdx` ON `splitPresets` (`name`);

CREATE TABLE `toolConfigs` (
	`id` text PRIMARY KEY NOT NULL,
	`provider` text,
	`toolId` text,
	`customArgs` text,
	`args` text,
	`env` text,
	`toolsToToolsetsId` text DEFAULT '__MSTY__DEFAULT__NO_TOOLSET__TOOL__',
	`extras` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`toolId`) REFERENCES `tools`(`id`) ON UPDATE no action ON DELETE cascade
);

CREATE UNIQUE INDEX `uniqueTool_ToolsetIdx` ON `toolConfigs` (`toolId`,`toolsToToolsetsId`);

CREATE TABLE `tools` (
	`id` text PRIMARY KEY NOT NULL,
	`toolId` text NOT NULL,
	`name` text NOT NULL,
	`config` text NOT NULL,
	`notes` text,
	`provider` text DEFAULT 'mcp',
	`compatibility` text,
	`colorIcon` text,
	`extras` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
, `folderId` text REFERENCES toolFolders(id));

CREATE UNIQUE INDEX `tools_toolId_unique` ON `tools` (`toolId`);

CREATE INDEX `toolsToolIdIdx` ON `tools` (`toolId`);

CREATE TABLE `toolsets` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`priority` real DEFAULT (unixepoch() * 1000) NOT NULL,
	`notes` text,
	`extras` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
, `folderId` text REFERENCES toolsetFolders(id));

CREATE UNIQUE INDEX `toolsets_name_unique` ON `toolsets` (`name`);

CREATE TABLE `toolsToToolsets` (
	`id` text PRIMARY KEY NOT NULL,
	`toolId` text,
	`toolsetId` text,
	`extras` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`toolId`) REFERENCES `tools`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`toolsetId`) REFERENCES `toolsets`(`id`) ON UPDATE no action ON DELETE cascade
);

CREATE TABLE `turnstiles` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`entries` text NOT NULL,
	`extras` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
, `description` text, `colorIcon` text, `folderId` text REFERENCES turnstileFolders(id), `fallbackModelInfo` text);

CREATE UNIQUE INDEX `turnstiles_name_unique` ON `turnstiles` (`name`);

CREATE INDEX `turnstilesNameIdx` ON `turnstiles` (`name`);

CREATE TABLE `workspaces` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`slug` text NOT NULL,
	`colorIcon` text,
	`extras` text,
	`isActive` integer DEFAULT false NOT NULL,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE UNIQUE INDEX `workspaces_slug_unique` ON `workspaces` (`slug`);

CREATE INDEX `workspacesSlugIdx` ON `workspaces` (`slug`);

CREATE VIRTUAL TABLE search USING fts5(
    extras,
    entity, 
    content,
    entityId
);

CREATE TRIGGER after_delete_messages
    AFTER DELETE ON conversationTextMessages
    FOR EACH ROW
BEGIN
    DELETE FROM search
    WHERE entityId = OLD.id AND entity = 'conversationTextMessages';
END;

CREATE TABLE `promptsLibraryFolders` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`colorIcon` text,
	`isExpanded` integer DEFAULT true NOT NULL,
	`sortOrder` integer DEFAULT -1 NOT NULL,
	`folderParentId` text,
	`extras` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`folderParentId`) REFERENCES `promptsLibraryFolders`(`id`) ON UPDATE no action ON DELETE cascade
);

CREATE INDEX `promptsLibraryFoldersNameIdx` ON `promptsLibraryFolders` (`name`);

CREATE TABLE `promptsLibraryPrompts` (
	`id` text PRIMARY KEY NOT NULL,
	`title` text NOT NULL,
	`text` text NOT NULL,
	`folderId` text NOT NULL,
	`source` text DEFAULT 'ootb' NOT NULL,
	`isBookmarked` integer DEFAULT false NOT NULL,
	`extras` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL, `lastUsedAt` text, `activeVersionId` text,
	FOREIGN KEY (`folderId`) REFERENCES `promptsLibraryFolders`(`id`) ON UPDATE no action ON DELETE cascade
);

CREATE INDEX `promptTitleIdx` ON `promptsLibraryPrompts` (`title`);

CREATE TABLE `promptsToTags` (
	`promptId` text NOT NULL,
	`tagId` text NOT NULL,
	PRIMARY KEY(`promptId`, `tagId`),
	FOREIGN KEY (`promptId`) REFERENCES `promptsLibraryPrompts`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`tagId`) REFERENCES `tags`(`id`) ON UPDATE no action ON DELETE cascade
);

CREATE TABLE `tags` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE UNIQUE INDEX `tags_name_unique` ON `tags` (`name`);

CREATE INDEX `tagNameIdx` ON `tags` (`name`);

CREATE TRIGGER after_insert_promptsLibrary
    AFTER INSERT ON promptsLibraryPrompts
    FOR EACH ROW
BEGIN
    INSERT INTO search (entity, entityId, content, extras)
    VALUES ('promptsLibraryPrompts', NEW.id, CONCAT(NEW.title, ' ', NEW.text), json_object('title', NEW.title));
END;

CREATE TRIGGER after_update_promptsLibrary
    AFTER UPDATE ON promptsLibraryPrompts
    FOR EACH ROW
BEGIN
    UPDATE search SET content = CONCAT(NEW.title, ' ', NEW.text), extras = json_object('title', NEW.title)
    WHERE entityId = NEW.id;
END;

CREATE TRIGGER after_delete_promptsLibrary
    AFTER DELETE ON promptsLibraryPrompts
    FOR EACH ROW
BEGIN
    DELETE FROM search
    WHERE entityId = OLD.id AND entity = 'promptsLibraryPrompts';
END;

CREATE TABLE `conversationTextMessageKnowledgeStackChunks`
(
    `id`                   text PRIMARY KEY               NOT NULL,
    `searchQuery`          text                           NOT NULL,
    `knowledgeStackIds`    text                           NOT NULL,
    `totalChunksRetrieved` integer                        NOT NULL,
    `chunks`               text                           NOT NULL,
    `querySettings`        text,
    `extras`               text,
    `createdAt`            text DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE `knowledgeStackFolders`
(
    `id`             text PRIMARY KEY                  NOT NULL,
    `name`           text                              NOT NULL,
    `colorIcon`      text,
    `isExpanded`     integer DEFAULT true              NOT NULL,
    `sortOrder`      integer DEFAULT -1                NOT NULL,
    `folderParentId` text,
    `extras`         text,
    `createdAt`      text    DEFAULT CURRENT_TIMESTAMP NOT NULL, `ignoreRules` text,
    FOREIGN KEY (`folderParentId`) REFERENCES `knowledgeStackFolders` (`id`) ON UPDATE no action ON DELETE cascade
);

CREATE INDEX `knowledgeStackFoldersNameIdx` ON `knowledgeStackFolders` (`name`);

CREATE TABLE `knowledgeStacks`
(
    `id`              text PRIMARY KEY                  NOT NULL,
    `title`           text                              NOT NULL,
    `text`            text,
    `source`          text    DEFAULT 'custom'          NOT NULL,
    `sortOrder`       integer DEFAULT -1                NOT NULL,
    `folderId`        text                              NOT NULL,
    `status`          text    DEFAULT 'draft'           NOT NULL,
    `files`           text,
    `notes`           text,
    `youTubeLinks`    text,
    `folders`         text,
    `obsidianVaults`  text,
    `composeStats`    text,
    `composeSettings` text                              NOT NULL,
    `querySettings`   text                              NOT NULL,
    `vectorInfo`      text,
    `extras`          text,
    `createdAt`       text    DEFAULT CURRENT_TIMESTAMP NOT NULL,
    `updatedAt`       text    DEFAULT CURRENT_TIMESTAMP NOT NULL, `webLinks` text, `conversations` text, `conversationProjects` text,
    FOREIGN KEY (`folderId`) REFERENCES `knowledgeStackFolders` (`id`) ON UPDATE no action ON DELETE cascade
);

CREATE INDEX `knowledgeStacksNameIdx` ON `knowledgeStacks` (`title`);

CREATE INDEX `knowledgeStacksFolderIdIdx` ON `knowledgeStacks` (`folderId`);

CREATE INDEX `knowledgeStacksStatusIdx` ON `knowledgeStacks` (`status`);

CREATE INDEX `knowledgeStacksUpdatedAtIdx` ON `knowledgeStacks` (`updatedAt`);

CREATE INDEX `knowledgeStacksCreatedAtIdx` ON `knowledgeStacks` (`createdAt`);

CREATE INDEX `knowledgeStacksStatusUpdatedAtCreatedAtIdx` ON `knowledgeStacks` (`status`, `updatedAt` DESC, `createdAt` DESC);

CREATE INDEX `knowledgeStackFoldersFolderParentIdIdx` ON `knowledgeStackFolders` (`folderParentId`);

CREATE INDEX `knowledgeStackFoldersCreatedAtIdx` ON `knowledgeStackFolders` (`createdAt`);

CREATE INDEX `conversationTextMessageKnowledgeStackChunksCreatedAtIdx` ON `conversationTextMessageKnowledgeStackChunks` (`createdAt`);

CREATE INDEX `conversationTextMessageKnowledgeStackChunksSearchQueryIdx` ON `conversationTextMessageKnowledgeStackChunks` (`searchQuery`);

CREATE TRIGGER update_knowledgeStacks_updatedAt
    AFTER UPDATE
    ON knowledgeStacks
    FOR EACH ROW
    WHEN OLD.title != NEW.title
        OR OLD.text != NEW.text
        OR OLD.source != NEW.source
        OR OLD.sortOrder != NEW.sortOrder
        OR OLD.folderId != NEW.folderId
        OR OLD.status != NEW.status
        OR OLD.files != NEW.files
        OR OLD.notes != NEW.notes
        OR OLD.youTubeLinks != NEW.youTubeLinks
        OR OLD.folders != NEW.folders
        OR OLD.obsidianVaults != NEW.obsidianVaults
        OR OLD.composeStats != NEW.composeStats
        OR OLD.composeSettings != NEW.composeSettings
        OR OLD.querySettings != NEW.querySettings
        OR OLD.vectorInfo != NEW.vectorInfo
        OR OLD.extras != NEW.extras
BEGIN
    UPDATE knowledgeStacks SET updatedAt = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TABLE `personaFolders` (
                                  `id` text PRIMARY KEY NOT NULL,
                                  `name` text NOT NULL,
                                  `colorIcon` text,
                                  `isExpanded` integer DEFAULT true NOT NULL,
                                  `sortOrder` integer DEFAULT -1 NOT NULL,
                                  `extras` text,
                                  `createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX `personaFoldersNameIdx` ON `personaFolders` (`name`);

CREATE TABLE "personas" (
                                `id` text PRIMARY KEY NOT NULL,
                                `name` text NOT NULL UNIQUE,
                                `colorIcon` text,
                                `description` text,
                                `folderId` text NOT NULL,
                                `systemPrompt` text NOT NULL,
                                `partialRTDInfo` text,
                                `partialSelectableAttachments` text,
                                `partialToolsetsInfo` text,
                                `partialLiveContextsInfo` text,
                                `contextShieldInfo` text,
                                `partialModelInfo` text,
                                `fewShotPrompts` text,
                                `extras` text,
                                `createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL, `partialKnowledgeStacksInfo` text, `activeVersionId` text,
                                FOREIGN KEY (`folderId`) REFERENCES `personaFolders`(`id`) ON DELETE CASCADE
);

CREATE INDEX `personasNameIdx` ON `personas` (`name`);

CREATE TABLE `notifications` (
	`id` text PRIMARY KEY NOT NULL,
	`level` text NOT NULL,
	`message` text NOT NULL,
	`metadata` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX `notificationsLevelIdx` ON `notifications` (`level`);

CREATE INDEX `notificationsCreatedAtIdx` ON `notifications` (`createdAt`);

CREATE TABLE `shadowPersonaOutputs`
(
    `id`                     text PRIMARY KEY               NOT NULL,
    `shadowPersonaId`        text                           NOT NULL,
    `conversationId`         text                           NOT NULL,
    `version`                integer                        NOT NULL,
    `content`                text                           NOT NULL,
    `modelInfo`              text,
    `toolCalls`              text,
    `completionTokensUsage`  text,
    `responseMetricsInfo`    text,
    `metadata`               text,
    `triggerMessageIds`      text,
    `processingTimeMs`       integer,
    `tokenCount`             integer,
    `extras`                 text,
    `createdAt`              text DEFAULT CURRENT_TIMESTAMP NOT NULL,
    `knowledgeStacksInfo`    text,
    `knowledgeStackChunksId` text,
    `rtdId`                  text,
    `liveContextResultsIds`  text,
    `attachments`            text,
    FOREIGN KEY (`shadowPersonaId`) REFERENCES `shadowPersonas` (`id`) ON UPDATE no action ON DELETE cascade,
    FOREIGN KEY (`knowledgeStackChunksId`) REFERENCES `conversationTextMessageKnowledgeStackChunks` (`id`) ON UPDATE no action ON DELETE set null,
    FOREIGN KEY (`rtdId`) REFERENCES `conversationTextMessageRealTimeData` (`id`) ON UPDATE no action ON DELETE set null
);

CREATE TABLE `shadowPersonaQueue`
(
    `id`                        text PRIMARY KEY               NOT NULL,
    `conversationId`            text                           NOT NULL,
    `shadowPersonaId`           text                           NOT NULL,
    `status`                    text                           NOT NULL,
    `priority`                  text                           NOT NULL,
    `contextSnapshot`           text                           NOT NULL,
    `conversationSnapshot`      text,
    `processingMetadata`        text,
    `positionInQueue`           integer,
    `estimatedProcessingTimeMs` integer,
    `createdAt`                 text DEFAULT CURRENT_TIMESTAMP NOT NULL,
    `updatedAt`                 text DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE `shadowPersonas`
(
    `id`          text PRIMARY KEY               NOT NULL,
    `name`        text                           NOT NULL,
    `description` text,
    `personaId`   text                           NOT NULL,
    `config`      text                           NOT NULL,
    `extras`      text,
    `createdAt`   text DEFAULT CURRENT_TIMESTAMP NOT NULL,
    `updatedAt`   text DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE `promptsComparisons`
(
    `id`        text PRIMARY KEY               NOT NULL,
    `promptId`  text                           NOT NULL,
    `runAId`    text                           NOT NULL,
    `runBId`    text                           NOT NULL,
    `winner`    text                           NOT NULL,
    `notes`     text,
    `createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
    `extras`    text,
    FOREIGN KEY (`promptId`) REFERENCES `promptsLibraryPrompts` (`id`) ON UPDATE no action ON DELETE cascade,
    FOREIGN KEY (`runAId`) REFERENCES `promptsTestRuns` (`id`) ON UPDATE no action ON DELETE cascade,
    FOREIGN KEY (`runBId`) REFERENCES `promptsTestRuns` (`id`) ON UPDATE no action ON DELETE cascade
);

CREATE INDEX `comparisonPromptIdx` ON `promptsComparisons` (`promptId`);

CREATE INDEX `comparisonRunAIdx` ON `promptsComparisons` (`runAId`);

CREATE INDEX `comparisonRunBIdx` ON `promptsComparisons` (`runBId`);

CREATE TABLE `promptsTestRuns`
(
    `id`                  text PRIMARY KEY                  NOT NULL,
    `promptId`            text                              NOT NULL,
    `versionId`           text                              NOT NULL,
    `modelId`             text                              NOT NULL,
    `modelName`           text                              NOT NULL,
    `providerId`          text                              NOT NULL,
    `temperature`         real,
    `maxTokens`           integer,
    `topP`                real,
    `advancedParams`      text,
    `systemPromptEnabled` integer DEFAULT false             NOT NULL,
    `systemPrompt`        text,
    `variableValues`      text,
    `resolvedPrompt`      text                              NOT NULL,
    `output`              text,
    `error`               text,
    `latencyMs`           integer,
    `inputTokens`         integer,
    `outputTokens`        integer,
    `rating`              integer,
    `notes`               text,
    `createdAt`           text    DEFAULT CURRENT_TIMESTAMP NOT NULL,
    `extras`              text,
    FOREIGN KEY (`promptId`) REFERENCES `promptsLibraryPrompts` (`id`) ON UPDATE no action ON DELETE cascade,
    FOREIGN KEY (`versionId`) REFERENCES `promptsVersions` (`id`) ON UPDATE no action ON DELETE cascade
);

CREATE INDEX `promptTestRunIdx` ON `promptsTestRuns` (`promptId`);

CREATE INDEX `versionTestRunIdx` ON `promptsTestRuns` (`versionId`);

CREATE TABLE `promptsVariableValues`
(
    `id`           text PRIMARY KEY               NOT NULL,
    `promptId`     text                           NOT NULL,
    `variableName` text                           NOT NULL,
    `value`        text                           NOT NULL,
    `updatedAt`    text DEFAULT CURRENT_TIMESTAMP NOT NULL,
    FOREIGN KEY (`promptId`) REFERENCES `promptsLibraryPrompts` (`id`) ON UPDATE no action ON DELETE cascade
);

CREATE INDEX `variableValuePromptIdx` ON `promptsVariableValues` (`promptId`, `variableName`);

CREATE UNIQUE INDEX `promptVariableUnique` ON `promptsVariableValues` (`promptId`, `variableName`);

CREATE TABLE `promptsVersions`
(
    `id`            text PRIMARY KEY               NOT NULL,
    `promptId`      text                           NOT NULL,
    `versionNumber` integer                        NOT NULL,
    `title`         text                           NOT NULL,
    `text`          text                           NOT NULL,
    `variables`     text,
    `changelog`     text,
    `createdAt`     text DEFAULT CURRENT_TIMESTAMP NOT NULL,
    `extras`        text,
    FOREIGN KEY (`promptId`) REFERENCES `promptsLibraryPrompts` (`id`) ON UPDATE no action ON DELETE cascade
);

CREATE INDEX `promptVersionIdx` ON `promptsVersions` (`promptId`, `versionNumber`);

CREATE TABLE `crewPersonas`
(
    `id`            text PRIMARY KEY                  NOT NULL,
    `crewId`        text                              NOT NULL,
    `personaId`     text                              NOT NULL,
    `stackRank`     integer DEFAULT 0                 NOT NULL,
    `shouldRespond` integer DEFAULT true              NOT NULL,
    `createdAt`     text    DEFAULT CURRENT_TIMESTAMP NOT NULL,
    FOREIGN KEY (`crewId`) REFERENCES `crews` (`id`) ON UPDATE no action ON DELETE cascade
);

CREATE TABLE `crews`
(
    `id`            text PRIMARY KEY               NOT NULL,
    `name`          text                           NOT NULL,
    `description`   text,
    `colorIcon`     text,
    `responseMode`  text DEFAULT 'manual'          NOT NULL,
    `executionMode` text DEFAULT 'sequential'      NOT NULL,
    `contextMode`   text DEFAULT 'independent'     NOT NULL,
    `extras`        text,
    `createdAt`     text DEFAULT CURRENT_TIMESTAMP NOT NULL,
    `updatedAt`     text DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE `liveContextFolders` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`colorIcon` text,
	`isExpanded` integer DEFAULT true NOT NULL,
	`sortOrder` integer DEFAULT -1 NOT NULL,
	`extras` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX `liveContextFoldersNameIdx` ON `liveContextFolders` (`name`);

CREATE TABLE `toolFolders` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`colorIcon` text,
	`isExpanded` integer DEFAULT true NOT NULL,
	`sortOrder` integer DEFAULT -1 NOT NULL,
	`extras` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX `toolFoldersNameIdx` ON `toolFolders` (`name`);

CREATE TABLE `toolsetFolders` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`colorIcon` text,
	`isExpanded` integer DEFAULT true NOT NULL,
	`sortOrder` integer DEFAULT -1 NOT NULL,
	`extras` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX `toolsetFoldersNameIdx` ON `toolsetFolders` (`name`);

CREATE INDEX `liveContextsFolderIdIdx` ON `liveContexts` (`folderId`);

CREATE INDEX `toolsFolderIdIdx` ON `tools` (`folderId`);

CREATE INDEX `toolsetsFolderIdIdx` ON `toolsets` (`folderId`);

CREATE TABLE `personaVersions` (
  `id` text PRIMARY KEY NOT NULL,
  `personaId` text NOT NULL,
  `versionNumber` integer NOT NULL,
  `name` text NOT NULL,
  `colorIcon` text,
  `description` text,
  `systemPrompt` text NOT NULL,
  `partialRTDInfo` text,
  `partialSelectableAttachments` text,
  `partialToolsetsInfo` text,
  `partialKnowledgeStacksInfo` text,
  `partialLiveContextsInfo` text,
  `contextShieldInfo` text,
  `partialModelInfo` text,
  `fewShotPrompts` text,
  `tags` text,
  `extras` text,
  `changelog` text,
  `createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
  FOREIGN KEY (`personaId`) REFERENCES `personas`(`id`) ON UPDATE no action ON DELETE cascade
);

CREATE INDEX `personaVersionIdx` ON `personaVersions` (`personaId`, `versionNumber`);

CREATE UNIQUE INDEX `personaVersionUniqueIdx` ON `personaVersions` (`personaId`, `versionNumber`);

CREATE TABLE `personasToTags` (
  `personaId` text NOT NULL,
  `tagId` text NOT NULL,
  PRIMARY KEY (`personaId`, `tagId`),
  FOREIGN KEY (`personaId`) REFERENCES `personas`(`id`) ON UPDATE no action ON DELETE cascade,
  FOREIGN KEY (`tagId`) REFERENCES `tags`(`id`) ON UPDATE no action ON DELETE cascade
);

CREATE UNIQUE INDEX `conversationTextChatSplits_agentSessionId_unique` ON `conversationTextChatSplits` (`agentSessionId`);

CREATE INDEX `conversationTextChatSplits_agentSessionId_idx` ON `conversationTextChatSplits` (`agentSessionId`);

CREATE INDEX `conversationTextChatSplits_conversationId_idx` ON `conversationTextChatSplits` (`conversationId`);

CREATE UNIQUE INDEX `conversationTexts_sourceAgentId_alienConversationId_unique` ON `conversationTexts` (`sourceAgentId`, `alienConversationId`);

CREATE INDEX `conversationTexts_sourceAgentId_idx` ON `conversationTexts` (`sourceAgentId`);

CREATE INDEX `conversationTexts_alienConversationId_idx` ON `conversationTexts` (`alienConversationId`);

CREATE TRIGGER conversationTextMessages_autocorrect_self_parent_insert
AFTER INSERT ON conversationTextMessages
FOR EACH ROW
WHEN NEW.branchParentId = NEW.id
BEGIN
  UPDATE conversationTextMessages
  SET branchParentId = NULL
  WHERE id = NEW.id;
END;

CREATE TRIGGER conversationTextMessages_autocorrect_self_parent_update
AFTER UPDATE OF branchParentId ON conversationTextMessages
FOR EACH ROW
WHEN NEW.branchParentId = NEW.id
BEGIN
  UPDATE conversationTextMessages
  SET branchParentId = NULL
  WHERE id = NEW.id;
END;

CREATE TABLE `agentModePlans`
(
    `id`              text PRIMARY KEY                  NOT NULL,
    `chatSplitId`     text                              NOT NULL,
    `entries`         text                              NOT NULL,
    `isCurrent`       integer DEFAULT false             NOT NULL,
    `totalDurationMs` integer,
    `extras`          text,
    `createdAt`       text    DEFAULT CURRENT_TIMESTAMP NOT NULL,
    FOREIGN KEY (`chatSplitId`) REFERENCES `conversationTextChatSplits` (`id`) ON UPDATE no action ON DELETE cascade
);

CREATE INDEX `agentModePlans_chatSplitId_idx` ON `agentModePlans` (`chatSplitId`);

CREATE TRIGGER after_insert_messages
AFTER INSERT ON conversationTextMessages
FOR EACH ROW
BEGIN
  INSERT INTO search (entity, entityId, content, extras)
  VALUES (
    'conversationTextMessages',
    NEW.id,
    COALESCE(
      NULLIF(
        CASE
          WHEN json_type(NEW.content, '$') = 'array' THEN (
            SELECT group_concat(json_extract(value, '$.text'), ' ')
            FROM json_each(NEW.content)
            WHERE json_extract(value, '$.type') = 'text'
          )
          ELSE json_extract(NEW.content, '$.text')
        END,
        ''
      ),
      NULLIF(
        CASE
          WHEN json_extract(NEW.extras, '$.agentModeData.messageType') = 'agent' THEN (
            SELECT group_concat(json_extract(value, '$.content'), '')
            FROM json_each(COALESCE(json_extract(NEW.extras, '$.agentModeData.turnEvents'), '[]'))
            WHERE json_extract(value, '$.type') = 'assistant_output'
          )
          ELSE NULL
        END,
        ''
      )
    ),
    json_object('chatSplitId', NEW.chatSplitId)
  );
END;

CREATE TRIGGER after_update_messages
AFTER UPDATE ON conversationTextMessages
FOR EACH ROW
BEGIN
  UPDATE search
  SET content = COALESCE(
    NULLIF(
      CASE
        WHEN json_type(NEW.content, '$') = 'array' THEN (
          SELECT group_concat(json_extract(value, '$.text'), ' ')
          FROM json_each(NEW.content)
          WHERE json_extract(value, '$.type') = 'text'
        )
        ELSE json_extract(NEW.content, '$.text')
      END,
      ''
    ),
    NULLIF(
      CASE
        WHEN json_extract(NEW.extras, '$.agentModeData.messageType') = 'agent' THEN (
          SELECT group_concat(json_extract(value, '$.content'), '')
          FROM json_each(COALESCE(json_extract(NEW.extras, '$.agentModeData.turnEvents'), '[]'))
          WHERE json_extract(value, '$.type') = 'assistant_output'
        )
        ELSE NULL
      END,
      ''
    )
  )
  WHERE entityId = NEW.id;
END;

CREATE TABLE `userPersonas` (
  `id` TEXT PRIMARY KEY NOT NULL,
  `name` TEXT NOT NULL,
  `description` TEXT,
  `folderId` TEXT,
  `avatarImageDataUrl` TEXT,
  `avatarIconName` TEXT,
  `activeVersionId` TEXT,
  `memories` TEXT,
  `createdAt` TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL,
  `updatedAt` TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX `userPersonasNameIdx` ON `userPersonas` (`name`);

CREATE TABLE `userPersonaVersions` (
  `id` TEXT PRIMARY KEY NOT NULL,
  `userPersonaId` TEXT NOT NULL,
  `versionNumber` INTEGER NOT NULL,
  `name` TEXT NOT NULL,
  `description` TEXT,
  `avatarImageDataUrl` TEXT,
  `avatarIconName` TEXT,
  `memories` TEXT,
  `changelog` TEXT,
  `createdAt` TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL,
  `updatedAt` TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL,
  FOREIGN KEY (`userPersonaId`) REFERENCES `userPersonas`(`id`) ON UPDATE no action ON DELETE cascade
);

CREATE INDEX `userPersonaVersionIdx` ON `userPersonaVersions` (`userPersonaId`, `versionNumber`);

CREATE UNIQUE INDEX `userPersonaVersionUniqueIdx` ON `userPersonaVersions` (`userPersonaId`, `versionNumber`);

CREATE TABLE `skillFolders` (
  `id` text PRIMARY KEY NOT NULL,
  `name` text NOT NULL,
  `colorIcon` text,
  `isExpanded` integer DEFAULT true NOT NULL,
  `sortOrder` integer DEFAULT -1 NOT NULL,
  `extras` text,
  `createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX `skillFoldersNameIdx` ON `skillFolders` (`name`);

CREATE TABLE "skill_preferences" (
  `id` text PRIMARY KEY NOT NULL,
  `skillId` text NOT NULL,
  `isEnabled` text DEFAULT 'true' NOT NULL,
  `folderId` text NOT NULL REFERENCES `skillFolders`(`id`) ON DELETE cascade,
  `extras` text,
  `createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE UNIQUE INDEX `skill_preferences_skillId_unique` ON `skill_preferences` (`skillId`);

CREATE INDEX `skillPreferencesSkillIdIdx` ON `skill_preferences` (`skillId`);

CREATE INDEX `skillPreferencesFolderIdIdx` ON `skill_preferences` (`folderId`);

CREATE TABLE `turnstileFolders` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`colorIcon` text,
	`isExpanded` integer DEFAULT true NOT NULL,
	`sortOrder` integer DEFAULT -1 NOT NULL,
	`extras` text,
	`createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX `turnstileFoldersNameIdx` ON `turnstileFolders` (`name`);

CREATE TABLE `knowledgeStackComposeProgress` (
  `id` text PRIMARY KEY NOT NULL,
  `knowledgeStackId` text NOT NULL REFERENCES `knowledgeStacks`(`id`) ON DELETE cascade,
  `itemType` text NOT NULL,
  `itemId` text NOT NULL,
  `processingStatus` text NOT NULL,
  `error` text,
  `createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
  `updatedAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
, `checkpoint` text);

CREATE INDEX `knowledgeStackComposeProgressStackIdx`
ON `knowledgeStackComposeProgress` (`knowledgeStackId`);

CREATE UNIQUE INDEX `knowledgeStackComposeProgressItemIdx`
ON `knowledgeStackComposeProgress` (`knowledgeStackId`, `itemType`, `itemId`);

CREATE TABLE `attachmentsStudioFolders` (
  `id` text PRIMARY KEY NOT NULL,
  `name` text NOT NULL,
  `colorIcon` text,
  `isExpanded` integer DEFAULT true NOT NULL,
  `sortOrder` integer DEFAULT -1 NOT NULL,
  `folderParentId` text REFERENCES `attachmentsStudioFolders`(`id`) ON DELETE cascade,
  `extras` text,
  `createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX `attachmentsStudioFoldersNameIdx` ON `attachmentsStudioFolders` (`name`);

CREATE TABLE "attachments" (
  `id` text PRIMARY KEY NOT NULL,
  `name` text NOT NULL,
  `type` text NOT NULL,
  `folderId` text NOT NULL REFERENCES `attachmentsStudioFolders`(`id`) ON DELETE cascade,
  `metadata` text NOT NULL,
  `shortDescription` text,
  `longDescription` text,
  `tags` text,
  `processingStatus` text DEFAULT 'notProcessed' NOT NULL,
  `processedAt` text,
  `fileId` text NOT NULL UNIQUE,
  `extras` text,
  `updatedAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
  `createdAt` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX `attachmentFileIdIdx` ON `attachments` (`fileId`);

CREATE INDEX `attachmentFolderIdIdx` ON `attachments` (`folderId`);

CREATE INDEX `attachmentProcessingStatusIdx` ON `attachments` (`processingStatus`);

CREATE INDEX conversationTexts_archivedAt_idx ON conversationTexts (archivedAt);

CREATE INDEX conversationTexts_lastActivityAt_idx ON conversationTexts (lastActivityAt);

CREATE INDEX conversationTexts_projectId_idx ON conversationTexts (projectId);

CREATE TRIGGER conversationTextMessages_after_insert_lastActivity
    AFTER INSERT ON conversationTextMessages
    FOR EACH ROW
    BEGIN
      UPDATE conversationTexts
      SET lastActivityAt = COALESCE(NEW.updatedAt, CURRENT_TIMESTAMP)
      WHERE id = (
        SELECT conversationId
        FROM conversationTextChatSplits
        WHERE id = NEW.chatSplitId
      );
    END;

CREATE TRIGGER conversationTextMessages_after_update_touch_timestamp
    AFTER UPDATE ON conversationTextMessages
    FOR EACH ROW
    WHEN OLD.updatedAt = NEW.updatedAt
    BEGIN
      UPDATE conversationTextMessages
      SET updatedAt = CURRENT_TIMESTAMP
      WHERE id = NEW.id;
    END;

CREATE TRIGGER conversationTextMessages_after_update_lastActivity
    AFTER UPDATE ON conversationTextMessages
    FOR EACH ROW
    WHEN NEW.updatedAt != OLD.updatedAt
    BEGIN
      UPDATE conversationTexts
      SET lastActivityAt = NEW.updatedAt
      WHERE id = (
        SELECT conversationId
        FROM conversationTextChatSplits
        WHERE id = NEW.chatSplitId
      );
    END;

INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('6cf719b1d685f6cbfafcd5c065bae7d793d548528eec072e52840f2caf306368', 1742585933237);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('08a541919b4528add10eb3aac5fa8f64fcb41e307995f2d3394f767f97ee4181', 1745833862398);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('2b017fade4667b85608456b32400b4681ca3fa7a156c3b0f7c5b54fc372182a7', 1748550272048);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('d326058931c76431164de092042226351590a347966a617bdb5b1e862900e98d', 1753148704874);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('da6afbf8b635796d6d2b2472dd1c6c837ca5d659a2a9bfa7dd909857885ec912', 1753201704028);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('2a7108f59ebb948fea1fb2f0faa76749abf8e1b522dcfcbac38b7080e2a0d5ab', 1753303086940);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('b93bbad69a72ebb3f2139fb07512fde69020655c314dfb7d98628a60625b72c6', 1755196732226);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('be7cca05c4f9455d94bffe26fe209c5a4c0d45f7f895f3bf3c044e036dd1b570', 1755814495864);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('1c2eab64c6a6d35c9f91a69fe634edb40fe4a1e04e25a0a22c6b47a0e02c9cfc', 1759254131777);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('9c3b46ff803458491a510f0ccbb080cbdf9df8208b7273181027e4b5642dc1a8', 1759342135437);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('9fa312bbf21ea974c14415beb11c4b74eadd005c69b7070fcfce2faf8f58e887', 1759877385954);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('33ccc73c165fbe520c016798c2b59996a5892f6543112cb6fa05080568efa182', 1760713739904);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('b2e277fcf71b4a9ad86eaebb955ea6b9651014a3dcd26be9591686a42e6ca360', 1763048232306);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('4b2d26d0daf5a18e8e8288d6a3eaa1cfaa1b89160df68e30248850a6df5bf410', 1764349256121);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('e7a1a6aa85ce5e1ea13593ff87348b9022062f0421bd5c8b664e06ac41284bdd', 1768591540919);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('99a321276e3b529dee9c76bfdb59dc91077bbd8a25bfc7cca420e8ddc20d2cf1', 1768956332661);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('f390f33805545cf4c6f2a4ddd96dc78f5fc120b47bad2183179586a6a90f0c85', 1769013756687);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('2858063953e5a0e86eef0f2afb57d54c7785b286ca53e26f68d2da985b3cd5a9', 1769542582470);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('1c4c2538648064057b82cf23372433a627c8255b916bade5afea78e7ee94d351', 1772281800000);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('07024b22f1e6dd9f9d605dcab5107d9a6dfb2330a04a3e078f6d7b823e59ac55', 1772330228059);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('422e5e7d3125eff5649e8be7fd803df28bda4b503629b8205abe5c173815e237', 1772648852125);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('2fcd643c56aea2dfe49d0fc366c6e1d7ea1bdf53ccda0df7bbfea81a24e517d2', 1772723700000);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('11b47a5e66ec50c317e6fe85a30e5987c5f376256c44cb6a19599cfd9f97e845', 1773849600000);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('34fb67e8b4e7d10e7a5baba0363ee162f8116fc99e0281a04a513039ad2f8055', 1774465409140);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('f8d58dd4c91d6eca064ba3ada8560b89ceee08d81d9764d429cd5f2ddba74eb4', 1774469700000);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('21efd4bb5d5b3883c349b818c3386c24ba21d7952da61ace260db65bf8b09e52', 1774612800000);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('da9ebc41f44b5c8e35981c0375cc29f46c0d47c7ea670746210b3f9c54659916', 1775041200000);
INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('3167d24f06196a4b55ab08900d5f9eb86089357a7865d2d7cd0105f2490f1b89', 1777333486000);
