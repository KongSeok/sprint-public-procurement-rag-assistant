# Data Model Specification

Defines semantic meaning of entities.
SQL schema must conform to this document.
Latest physical schema: lnf-migration.sql (bonus entities included there).

---

## User
Represents a system participant.

Rules:
- Multiple roles per user (stored as roles array or user_roles relation)
- BLOCKED users are read-only

Fields:
userId, username, passwordHash, role, roles, status, affiliation,  
displayName, phone, email, createdAt

---

## Lost
Represents a lost item report.

Rules:
- Created as OPEN
- CLOSED is terminal
- Only one active handover per lost at a time

Fields:
lostId, userId, category, categoryEtcLabel, title, titleEn, description, descriptionEn, imageUrl,  
lostAt, lostPlace, rewardAmount, status, createdAt

---

## Found
Represents a found item.

Rules:
- Only one active handover per found at a time
- IN_HANDOVER blocks modification

Fields:
foundId, ownerUserId, category, categoryEtcLabel, title, titleEn, description, descriptionEn, imageUrl,  
foundAt, foundPlace, storageType, storageLocation,  
status, createdAt

---

## Handover
Represents the workflow core.

Rules:
- Central state authority
- Completion triggers cross-entity sync

Fields:
handoverId, lostId, foundId, requesterId, responderId,  
method, scheduleAt, meetPlace, status,  
acceptedAt, verifiedAt, approvedAt, completedAt, canceledAt, createdAt

Courier Extension:
courierStatus, courierUpdatedAt

---

## Message
Handover-scoped chat message.

Fields:
messageId, handoverId, senderId, content, createdAt

---

## Notification
Stored system event.

Fields:
notificationId, userId, type, targetType, targetId, message, isRead, createdAt

---

## Report
Moderation report.

Fields:
reportId, targetType, targetId, reporterId, reason, status, createdAt

---

## Favorite
User bookmarked item reference.

Fields:
favoriteId, userId, targetType, targetId, createdAt
