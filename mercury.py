import discord
from discord.ext import commands
from discord.ui import Modal, TextInput, View, Button
import asyncio
import datetime
import os

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix='/', intents=intents)
tree = bot.tree

# Звуковые файлы
remind_sound = 'remind.mp3'
confirm_sound = 'confirm.mp3'
cancel_sound = 'cancel.mp3'
notification_sound = 'notification.mp3'

voice_channel_id = 1289694911234310155  # Замените на ID вашего голосового канала
text_channel_id = 1299347859828903977  # Замените на ID вашего текстового канала

# Словарь для хранения активных напоминаний
active_reminders = {}

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    await connect_to_voice_channel()
    try:
        synced = await tree.sync()
        print(f"Синхронизировано {len(synced)} команд")
    except Exception as e:
        print(f"Ошибка при синхронизации команд: {e}")
    print("Бот готов к работе")

@bot.event
async def on_voice_state_update(member, before, after):
    if member == bot.user:
        if after.channel is None or after.channel.id != voice_channel_id:
            print("Бот был отключен или перемещен из целевого канала. Попытка переподключения...")
            await attempt_reconnect()

async def attempt_reconnect():
    for attempt in range(5):
        try:
            await connect_to_voice_channel()
            print(f"Успешно переподключился после {attempt + 1} попытки")
            break
        except Exception as e:
            print(f"Попытка {attempt + 1} не удалась: {e}")
            await asyncio.sleep(5)

async def connect_to_voice_channel():
    voice_channel = bot.get_channel(voice_channel_id)
    if voice_channel:
        try:
            if bot.voice_clients:
                for vc in bot.voice_clients:
                    if vc.guild == voice_channel.guild:
                        await vc.disconnect()
            await voice_channel.connect(timeout=60, reconnect=True)
            print(f"Подключен к голосовому каналу: {voice_channel.name}")
        except Exception as e:
            print(f"Ошибка при подключении к голосовому каналу: {e}")
            raise
    else:
        print(f"Голосовой канал с ID {voice_channel_id} не найден")
        raise ValueError("Целевой голосовой канал не найден")

@tree.command(name="remind", description="Set a reminder")
async def remind(interaction: discord.Interaction):
    text_channel = bot.get_channel(text_channel_id)
    voice_channel = bot.get_channel(voice_channel_id)

    if interaction.channel.id != text_channel_id:
        await interaction.response.send_message(f"Эту команду можно использовать только в канале {text_channel.name}.", ephemeral=True)
        return

    if not interaction.user.voice or interaction.user.voice.channel.id != voice_channel_id:
        await interaction.response.send_message(f"Эту команду можно использовать только в голосовом канале {voice_channel.name}.", ephemeral=True)
        return

    print("Remind command called")
    modal = ReminderModal()
    await interaction.response.send_modal(modal)

class ReminderModal(Modal):
    def __init__(self):
        super().__init__(title="Set a Reminder")
        self.time_input = TextInput(label="Time (HH:MM)", placeholder="Введите время", max_length=5)
        self.message_input = TextInput(label="Message", placeholder="Введите сообщение")
        self.add_item(self.time_input)
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            time_value = self.time_input.value
            message_value = self.message_input.value

            try:
                hour, minute = map(int, time_value.split(':'))
                if not (0 <= hour < 24) or not (0 <= minute < 60):
                    raise ValueError("Неверный формат времени")
            except ValueError:
                await interaction.response.send_message("Неверный формат времени! Укажите в формате HH:MM.", ephemeral=True)
                return

            await play_sound(interaction, remind_sound)

            view = View(timeout=None)
            confirm_button = Button(label="Подтвердить", style=discord.ButtonStyle.green)
            cancel_button = Button(label="Отменить", style=discord.ButtonStyle.red)

            async def confirm_callback(confirm_interaction):
                await confirm_interaction.response.defer(ephemeral=True)
                print("Confirm button pressed")
                await stop_current_sound(confirm_interaction)
                await play_sound(confirm_interaction, confirm_sound)
                await confirm_interaction.message.delete()
                reminder_id = await schedule_reminder(confirm_interaction, time_value, message_value)
                active_reminders[reminder_id] = (time_value, message_value)

            async def cancel_callback(cancel_interaction):
                await cancel_interaction.response.defer(ephemeral=True)
                print("Cancel button pressed")
                await stop_current_sound(cancel_interaction)
                await play_sound(cancel_interaction, cancel_sound)
                await cancel_interaction.message.delete()

            confirm_button.callback = confirm_callback
            cancel_button.callback = cancel_callback
            view.add_item(confirm_button)
            view.add_item(cancel_button)

            await interaction.response.send_message("Подтвердите или отмените напоминание:", view=view)

        except Exception as e:
            print(f"Error while processing form: {e}")
            await interaction.response.send_message("Что-то пошло не так, попробуйте снова.", ephemeral=True)

@tree.command(name="all", description="Show all active reminders")
async def show_all_reminders(interaction: discord.Interaction):
    text_channel = bot.get_channel(text_channel_id)
    voice_channel = bot.get_channel(voice_channel_id)

    if interaction.channel.id != text_channel_id:
        await interaction.response.send_message(f"Эту команду можно использовать только в канале {text_channel.name}.", ephemeral=True)
        return

    if not interaction.user.voice or interaction.user.voice.channel.id != voice_channel_id:
        await interaction.response.send_message(f"Эту команду можно использовать только в голосовом канале {voice_channel.name}.", ephemeral=True)
        return

    current_time = datetime.datetime.now()
    active_reminders_copy = active_reminders.copy()

    # Удаляем прошедшие напоминания
    for reminder_id, (time_str, message) in active_reminders_copy.items():
        reminder_time = datetime.datetime.strptime(f"{current_time.date()} {time_str}", "%Y-%m-%d %H:%M")
        if reminder_time < current_time:
            del active_reminders[reminder_id]

    if not active_reminders:
        await interaction.response.send_message("Нет активных напоминаний.", ephemeral=True)
        return

    embed = discord.Embed(title="Активные напоминания", color=discord.Color.blue())
    for reminder_id, (time, message) in active_reminders.items():
        embed.add_field(name=f"ID: {reminder_id}", value=f"Время: {time}\nСообщение: {message}", inline=False)

    view = View(timeout=None)
    for reminder_id in active_reminders.keys():
        button = Button(label=f"Отменить {reminder_id}", style=discord.ButtonStyle.red, custom_id=str(reminder_id))
        button.callback = create_cancel_callback(reminder_id)
        view.add_item(button)

    exit_button = Button(label="Выход", style=discord.ButtonStyle.grey)
    exit_button.callback = create_exit_callback()
    view.add_item(exit_button)

    await interaction.response.send_message(embed=embed, view=view)

def create_cancel_callback(reminder_id):
    async def cancel_callback(interaction: discord.Interaction):
        await interaction.response.defer()
        if reminder_id in active_reminders:
            del active_reminders[reminder_id]
            await stop_current_sound(interaction)
            await play_sound(interaction, cancel_sound)

            # Обновляем сообщение, удаляя кнопку отмененного напоминания
            current_view = interaction.message.components[0]
            new_view = View(timeout=None)
            for item in current_view.children:
                if item.custom_id != str(reminder_id):
                    new_view.add_item(item)

            # Обновляем embed
            embed = interaction.message.embeds[0]
            embed.clear_fields()
            for r_id, (time, message) in active_reminders.items():
                embed.add_field(name=f"ID: {r_id}", value=f"Время: {time}\nСообщение: {message}", inline=False)

            await interaction.message.edit(embed=embed, view=new_view)
        else:
            await interaction.followup.send("Это напоминание уже не активно.", ephemeral=True)

    return cancel_callback

def create_exit_callback():
    async def exit_callback(interaction: discord.Interaction):
        await interaction.response.defer()
        await interaction.message.delete()

    return exit_callback

async def stop_current_sound(ctx):
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice_client and voice_client.is_playing():
        voice_client.stop()

async def play_sound(ctx, sound_file):
    try:
        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

        if not voice_client or not voice_client.is_connected() or voice_client.channel.id != voice_channel_id:
            print("Бот не подключён к целевому голосовому каналу. Попытка подключения...")
            await connect_to_voice_channel()
            voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

        if not voice_client or voice_client.channel.id != voice_channel_id:
            await ctx.followup.send("Не удалось подключиться к целевому голосовому каналу.", ephemeral=True)
            return

        if not os.path.exists(sound_file):
            print(f"Файл {sound_file} не найден.")
            await ctx.followup.send(f"Аудиофайл {sound_file} не найден.", ephemeral=True)
            return

        if voice_client.is_playing():
            voice_client.stop()

        voice_client.play(discord.FFmpegPCMAudio(sound_file))
        while voice_client.is_playing():
            await asyncio.sleep(1)
        print(f"Аудиофайл {sound_file} воспроизведён.")
    except Exception as e:
        print(f"Ошибка при воспроизведении звука: {e}")
        await ctx.followup.send("Произошла ошибка при воспроизведении звука.", ephemeral=True)

async def schedule_reminder(interaction, time, message):
    hour, minute = map(int, time.split(':'))
    now = datetime.datetime.now()
    reminder_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if reminder_time < now:
        reminder_time += datetime.timedelta(days=1)
    wait_time = (reminder_time - now).total_seconds()

    reminder_id = max(active_reminders.keys(), default=0) + 1
    active_reminders[reminder_id] = (time, message)

    await asyncio.sleep(wait_time)

    if reminder_id not in active_reminders:
        return  # Напоминание было отменено

    view = View(timeout=None)
    confirm_button = Button(label="Подтвердить", style=discord.ButtonStyle.green, emoji="✅")

    async def confirm_callback(confirm_interaction):
        await confirm_interaction.response.defer()
        print("Confirm button pressed")
        if reminder_id in active_reminders:
            del active_reminders[reminder_id]
            await stop_current_sound(confirm_interaction)
            await play_sound(confirm_interaction, confirm_sound)
            await confirm_interaction.message.delete()

    confirm_button.callback = confirm_callback
    view.add_item(confirm_button)

    reminder_message = await interaction.channel.send(f'Напоминание {reminder_id}: {message}', view=view)

    while reminder_id in active_reminders:
        await play_sound(interaction, notification_sound)
        await asyncio.sleep(20)
        try:
            await interaction.channel.fetch_message(reminder_message.id)
        except discord.NotFound:
            break

    if reminder_id in active_reminders:
        del active_reminders[reminder_id]

    return reminder_id


bot.run('')
