import 'package:flutter/material.dart';
import '../models/parcel.dart';
import '../services/chat_service.dart';
import '../services/chat_history_store.dart';

class ParcelChatSheet extends StatefulWidget {
  final Parcel parcel;

  const ParcelChatSheet({super.key, required this.parcel});

  @override
  State<ParcelChatSheet> createState() => _ParcelChatSheetState();
}

class _ParcelChatSheetState extends State<ParcelChatSheet> {
  final TextEditingController _controller = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  final List<_ChatMessage> _messages = [];
  final List<Map<String, String>> _history = [];
  bool _isTyping = false;

  static const _welcome =
      'Salut! Sunt Agronomul tău AI pentru această parcelă. Întreabă-mă orice despre '
      'sănătatea culturilor, decizii de însămânțare, combaterea dăunătorilor sau ce '
      'înseamnă starea vegetației pentru câmpul tău.';

  String get _historyKey => ChatHistoryStore.parcelKey(widget.parcel.id);

  @override
  void initState() {
    super.initState();
    _loadHistory();
  }

  Future<void> _loadHistory() async {
    final saved = await ChatHistoryStore.load(_historyKey);
    if (!mounted) return;
    setState(() {
      _messages.clear();
      _history.clear();
      if (saved.isEmpty) {
        _messages.add(const _ChatMessage(role: 'assistant', text: _welcome));
      } else {
        for (final m in saved) {
          final msg = _ChatMessage.fromJson(m);
          _messages.add(msg);
          if (!msg.isError) {
            _history.add({'role': msg.role, 'content': msg.text});
          }
        }
      }
    });
    _scrollToBottom();
  }

  Future<void> _persist() async {
    await ChatHistoryStore.save(
      _historyKey,
      _messages.map((m) => m.toJson()).toList(),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final text = _controller.text.trim();
    if (text.isEmpty || _isTyping) return;

    _controller.clear();
    setState(() {
      _messages.add(_ChatMessage(role: 'user', text: text));
      _isTyping = true;
    });
    _scrollToBottom();

    try {
      final answer = await ChatService.askParcel(
        widget.parcel.id,
        text,
        List.from(_history),
      );
      _history.add({'role': 'user', 'content': text});
      _history.add({'role': 'assistant', 'content': answer});

      if (mounted) {
        setState(() {
          _messages.add(_ChatMessage(role: 'assistant', text: answer));
          _isTyping = false;
        });
        _persist();
        _scrollToBottom();
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _messages.add(_ChatMessage(
            role: 'assistant',
            text: 'Ne pare rău, nu am putut contacta serviciul AI. ${e.toString().replaceFirst("Exception: ", "")}',
            isError: true,
          ));
          _isTyping = false;
        });
        _persist();
        _scrollToBottom();
      }
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    // Capture keyboard height here so the DraggableScrollableSheet builder
    // (which gets a child context) can use it to push content above the IME.
    final bottomInset = MediaQuery.viewInsetsOf(context).bottom;
    final navBarInset = MediaQuery.paddingOf(context).bottom;

    return DraggableScrollableSheet(
      initialChildSize: 0.75,
      minChildSize: 0.4,
      maxChildSize: 0.95,
      expand: false,
      builder: (_, scrollController) {
        return Padding(
          padding: EdgeInsets.only(bottom: bottomInset + navBarInset),
          child: Container(
          decoration: const BoxDecoration(
            color: Color(0xFF0D1B2A),
            borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
          ),
          child: Column(
            children: [
              // Drag handle
              Center(
                child: Container(
                  margin: const EdgeInsets.only(top: 12, bottom: 8),
                  width: 40,
                  height: 4,
                  decoration: BoxDecoration(
                    color: Colors.white24,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              // Header
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 4, 20, 12),
                child: Row(
                  children: [
                    const Icon(
                      Icons.agriculture,
                      color: Color(0xFF52B788),
                      size: 22,
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text(
                            'Agronom AI',
                            style: TextStyle(
                              color: Colors.white,
                              fontSize: 15,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                          Text(
                            widget.parcel.name,
                            style: const TextStyle(
                              color: Color(0xFF52B788),
                              fontSize: 12,
                            ),
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.close, color: Colors.white54),
                      onPressed: () => Navigator.of(context).pop(),
                    ),
                  ],
                ),
              ),
              const Divider(color: Colors.white12, height: 1),
              // Messages
              Expanded(
                child: ListView.builder(
                  controller: _scrollController,
                  padding: const EdgeInsets.all(16),
                  itemCount: _messages.length + (_isTyping ? 1 : 0),
                  itemBuilder: (context, index) {
                    if (index == _messages.length && _isTyping) {
                      return _TypingBubble();
                    }
                    return _MessageBubble(message: _messages[index]);
                  },
                ),
              ),
              // Input
              Container(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                decoration: BoxDecoration(
                  color: const Color(0xFF0D1B2A),
                  border: Border(
                    top: BorderSide(color: Colors.white.withValues(alpha: 0.08)),
                  ),
                ),
                child: SafeArea(
                  top: false,
                  child: Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: _controller,
                          style: const TextStyle(color: Colors.white, fontSize: 14),
                          maxLines: 3,
                          minLines: 1,
                          textInputAction: TextInputAction.send,
                          onSubmitted: (_) => _send(),
                          decoration: InputDecoration(
                            hintText: 'Întreabă despre această parcelă...',
                            hintStyle: TextStyle(
                              color: Colors.white.withValues(alpha: 0.35),
                              fontSize: 14,
                            ),
                            filled: true,
                            fillColor: Colors.white.withValues(alpha: 0.06),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(20),
                              borderSide: BorderSide.none,
                            ),
                            contentPadding: const EdgeInsets.symmetric(
                              horizontal: 16,
                              vertical: 10,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(width: 10),
                      GestureDetector(
                        onTap: _send,
                        child: Container(
                          width: 44,
                          height: 44,
                          decoration: BoxDecoration(
                            color: _isTyping
                                ? Colors.white12
                                : const Color(0xFF52B788),
                            shape: BoxShape.circle,
                          ),
                          child: const Icon(
                            Icons.send_rounded,
                            color: Colors.white,
                            size: 20,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
          );
      },
    );
  }
}

class _ChatMessage {
  final String role;
  final String text;
  final bool isError;

  const _ChatMessage({
    required this.role,
    required this.text,
    this.isError = false,
  });

  Map<String, dynamic> toJson() => {
        'role': role,
        'text': text,
        'isError': isError,
      };

  factory _ChatMessage.fromJson(Map<String, dynamic> json) => _ChatMessage(
        role: json['role'] as String? ?? 'assistant',
        text: json['text'] as String? ?? '',
        isError: json['isError'] as bool? ?? false,
      );
}

class _MessageBubble extends StatelessWidget {
  final _ChatMessage message;

  const _MessageBubble({required this.message});

  @override
  Widget build(BuildContext context) {
    final isUser = message.role == 'user';
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 12),
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.80,
        ),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          color: isUser
              ? const Color(0xFF52B788).withValues(alpha: 0.85)
              : (message.isError
                  ? const Color(0xFFE76F51).withValues(alpha: 0.15)
                  : Colors.white.withValues(alpha: 0.07)),
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(18),
            topRight: const Radius.circular(18),
            bottomLeft: isUser ? const Radius.circular(18) : const Radius.circular(4),
            bottomRight: isUser ? const Radius.circular(4) : const Radius.circular(18),
          ),
        ),
        child: Text(
          message.text,
          style: TextStyle(
            color: isUser ? Colors.white : Colors.white.withValues(alpha: 0.88),
            fontSize: 14,
            height: 1.5,
          ),
        ),
      ),
    );
  }
}

class _TypingBubble extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.07),
          borderRadius: const BorderRadius.only(
            topLeft: Radius.circular(18),
            topRight: Radius.circular(18),
            bottomRight: Radius.circular(18),
            bottomLeft: Radius.circular(4),
          ),
        ),
        child: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            _Dot(delay: 0),
            SizedBox(width: 4),
            _Dot(delay: 200),
            SizedBox(width: 4),
            _Dot(delay: 400),
          ],
        ),
      ),
    );
  }
}

class _Dot extends StatefulWidget {
  final int delay;
  const _Dot({required this.delay});

  @override
  State<_Dot> createState() => _DotState();
}

class _DotState extends State<_Dot> with SingleTickerProviderStateMixin {
  late AnimationController _ctrl;
  late Animation<double> _anim;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    );
    Future.delayed(Duration(milliseconds: widget.delay), () {
      if (mounted) _ctrl.repeat(reverse: true);
    });
    _anim = Tween<double>(begin: 0.3, end: 1.0).animate(
      CurvedAnimation(parent: _ctrl, curve: Curves.easeInOut),
    );
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: _anim,
      child: Container(
        width: 7,
        height: 7,
        decoration: const BoxDecoration(
          color: Color(0xFF52B788),
          shape: BoxShape.circle,
        ),
      ),
    );
  }
}
